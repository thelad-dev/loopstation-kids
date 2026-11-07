#!/usr/bin/env bash
# Installiert die Loopstation für den aktuellen Benutzer auf Linux.
#
# Systempakete (Python, PortAudio, libsndfile, ALSA, Qt-Bibliotheken, Compiler)
# kommen über den Paketmanager der Distribution, nur mit Rückfrage oder --yes.
# Alles andere landet im Benutzerverzeichnis:
#   ${XDG_DATA_HOME:-~/.local/share}/loopstation-kids/   Programm (venv), Einstellungen, Aufnahmen
#   ~/.local/bin/loopstation-kids                        Startbefehl
#   ${XDG_DATA_HOME:-~/.local/share}/applications/       Menüeintrag
#   ${XDG_DATA_HOME:-~/.local/share}/icons/hicolor/      Icon
#
# Aufruf: scripts/install-linux.sh [--yes] [--dry-run] [--uninstall [--purge]]
#         scripts/install-linux.sh --help
#
# Ohne bash (etwa ein frisches Alpine) mit "sh scripts/install-linux.sh"
# aufrufen: dann kommt ein Hinweis, wie bash nachinstalliert wird.

# Dieser Block muss reines POSIX-sh bleiben: er läuft auch unter dash/ash.
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    fi
    echo "Fehler: dieses Skript braucht bash. Bitte zuerst installieren, z. B. Alpine: sudo apk add bash" >&2
    exit 1
fi

set -euo pipefail

# Paketwerkzeuge wie apk, ldconfig oder rpm liegen teils in sbin, das im PATH
# normaler Benutzer fehlen kann.
PATH="${PATH:-/usr/bin:/bin}:/usr/sbin:/sbin"
export PATH

readonly APP_ID="loopstation-kids"
readonly APP_NAME="Loopstation"
readonly MIN_PYTHON="3.11"
readonly MARKER="# angelegt von scripts/install-linux.sh (${APP_ID})"

# Exit-Codes
readonly EXIT_ERROR=1
readonly EXIT_USAGE=2
readonly EXIT_PACKAGES=3

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly SCRIPT_DIR REPO_DIR

ASSUME_YES=0
DRY_RUN=0
UNINSTALL=0
PURGE=0
SKIP_SYSTEM=0
PYTHON_OVERRIDE=""

# Werden nach dem Einlesen der Optionen gesetzt.
DATA_HOME=""
APP_DIR=""
VENV_LINK=""
BIN_DIR=""
LAUNCHER=""
DESKTOP_FILE=""
ICON_FILE=""

# Ergebnis der Erkennung
OS_ID=""
OS_VERSION=""
OS_NAME=""
PM=""            # apt | dnf | pacman | zypper | apk
PYTHON=""        # gewählter Interpreter (absoluter Pfad)
PACKAGES=()      # benötigte Systempakete; "a|b" = erstes verfügbares
MISSING=()       # davon noch nicht installiert
ROOT_CMD=()      # leer = schon root, sonst sudo bzw. doas

# ---------------------------------------------------------------------------
# Ausgabe

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_BOLD=$'\033[1m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_GREEN=$'\033[32m'; C_OFF=$'\033[0m'
else
    C_BOLD=""; C_RED=""; C_YELLOW=""; C_GREEN=""; C_OFF=""
fi

step() { printf '%s==>%s %s\n' "$C_BOLD" "$C_OFF" "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '%s ok%s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn() { printf '%sHinweis:%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die() {
    local code="$1"
    shift
    printf '%sFehler:%s %s\n' "$C_RED" "$C_OFF" "$*" >&2
    exit "$code"
}

# Befehl ausführen oder im Trockenlauf nur anzeigen.
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '    [Trockenlauf] %s\n' "$(quote_cmd "$@")"
        return 0
    fi
    "$@"
}

run_root() {
    run ${ROOT_CMD[@]+"${ROOT_CMD[@]}"} "$@"
}

quote_cmd() {
    local out="" arg
    for arg in "$@"; do
        if [[ "$arg" =~ ^[A-Za-z0-9_./=:,+@%-]+$ ]]; then
            out+="$arg "
        else
            out+="$(printf '%q' "$arg") "
        fi
    done
    printf '%s' "${out% }"
}

# Text für einfache Anführungszeichen in sh maskieren.
sh_quote() {
    printf "'%s'" "${1//\'/\'\\\'\'}"
}

usage() {
    cat <<EOF
Installiert die ${APP_NAME} für den aktuellen Benutzer.

Aufruf: $(basename -- "$0") [Optionen]

  -y, --yes                 Systempakete ohne Rückfrage installieren (mit sudo/doas)
  -n, --dry-run             nur anzeigen, was passieren würde; nichts wird verändert
      --uninstall           Programm, Startbefehl, Menüeintrag und Icon entfernen
                            (Aufnahmen und Einstellungen bleiben erhalten)
      --purge               mit --uninstall: auch Aufnahmen, Protokoll und
                            Einstellungen löschen (mit Rückfrage)
      --no-system-packages  Systempakete weder prüfen noch installieren
      --python PFAD         diesen Python-Interpreter verwenden (mindestens ${MIN_PYTHON})
  -h, --help                diese Hilfe

Unterstützt: Debian, Ubuntu, Linux Mint und Verwandte (apt), Fedora, RHEL,
Rocky, AlmaLinux (dnf), Arch, Manjaro, EndeavourOS (pacman), openSUSE (zypper),
Alpine (apk). Auf anderen Distributionen mit --no-system-packages und den
Paketen aus der README.

Exit-Codes: 0 ok, ${EXIT_ERROR} Fehler, ${EXIT_USAGE} falscher Aufruf,
${EXIT_PACKAGES} Systempakete fehlen und konnten nicht installiert werden.
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -y|--yes) ASSUME_YES=1 ;;
            -n|--dry-run) DRY_RUN=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --purge) PURGE=1 ;;
            --no-system-packages) SKIP_SYSTEM=1 ;;
            --python)
                [ $# -ge 2 ] || die "$EXIT_USAGE" "--python braucht einen Pfad"
                PYTHON_OVERRIDE="$2"
                shift
                ;;
            --python=*) PYTHON_OVERRIDE="${1#--python=}" ;;
            -h|--help) usage; exit 0 ;;
            *) die "$EXIT_USAGE" "unbekannte Option: $1 (Hilfe: --help)" ;;
        esac
        shift
    done
    if [ "$PURGE" -eq 1 ] && [ "$UNINSTALL" -eq 0 ]; then
        die "$EXIT_USAGE" "--purge geht nur zusammen mit --uninstall"
    fi
}

# Ja/Nein-Frage. Ohne Terminal und ohne --yes gilt "nein".
confirm() {
    local answer=""
    if [ "$ASSUME_YES" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        warn "keine Rückfrage möglich (kein Terminal); mit --yes bestätigen"
        return 1
    fi
    printf '%s [j/N] ' "$1"
    read -r answer || return 1
    case "$answer" in
        j|J|ja|Ja|JA|y|Y|yes|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Umgebung

init_paths() {
    [ -n "${HOME:-}" ] || die "$EXIT_ERROR" "HOME ist nicht gesetzt"
    DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
    case "$DATA_HOME" in
        /*) ;;
        *) DATA_HOME="$HOME/.local/share" ;;  # XDG verlangt absolute Pfade
    esac
    APP_DIR="$DATA_HOME/$APP_ID"
    VENV_LINK="$APP_DIR/venv"
    BIN_DIR="$HOME/.local/bin"
    LAUNCHER="$BIN_DIR/$APP_ID"
    DESKTOP_FILE="$DATA_HOME/applications/$APP_ID.desktop"
    ICON_FILE="$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
}

check_platform() {
    [ "$(uname -s)" = "Linux" ] || die "$EXIT_ERROR" "dieses Skript ist nur für Linux"
    if [ "$(id -u)" -eq 0 ]; then
        warn "läuft als root: die Loopstation wird für root installiert (${HOME})." \
            "Üblich ist ein Aufruf als normaler Benutzer; Systempakete holt das Skript dann per sudo."
    fi
}

check_tools() {
    local tool missing=()
    for tool in awk grep sort tr head readlink dirname basename date id uname cp mv ln rm mkdir chmod; do
        command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        die "$EXIT_ERROR" "Grundwerkzeuge fehlen: ${missing[*]} (Pakete coreutils, grep, gawk bzw. awk)"
    fi
}

check_source() {
    [ -f "$REPO_DIR/pyproject.toml" ] && [ -d "$REPO_DIR/loopstation" ] \
        || die "$EXIT_ERROR" "Quelltext nicht gefunden: ${REPO_DIR} (das Skript muss im Ordner scripts/ des Repos liegen)"
}

detect_distro() {
    local id="" id_like="" version_id="" pretty=""
    if [ -r /etc/os-release ]; then
        # shellcheck source=/dev/null
        id="$(. /etc/os-release && printf '%s' "${ID:-}")"
        # shellcheck source=/dev/null
        id_like="$(. /etc/os-release && printf '%s' "${ID_LIKE:-}")"
        # shellcheck source=/dev/null
        version_id="$(. /etc/os-release && printf '%s' "${VERSION_ID:-}")"
        # shellcheck source=/dev/null
        pretty="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-}")"
    fi
    OS_ID="$id"
    OS_VERSION="$version_id"
    OS_NAME="${pretty:-${id:-unbekannt}}"

    local word
    for word in $id $id_like; do
        case "$word" in
            debian|ubuntu) PM="apt" ;;
            fedora|rhel|centos) PM="dnf" ;;
            arch|archlinux) PM="pacman" ;;
            suse|opensuse|opensuse-*|sles|sled) PM="zypper" ;;
            alpine) PM="apk" ;;
        esac
        [ -n "$PM" ] && break
    done

    # Erkannter Paketmanager muss auch da sein.
    case "$PM" in
        apt) command -v apt-get >/dev/null 2>&1 || PM="" ;;
        dnf) command -v dnf >/dev/null 2>&1 || PM="" ;;
        pacman) command -v pacman >/dev/null 2>&1 || PM="" ;;
        zypper) command -v zypper >/dev/null 2>&1 || PM="" ;;
        apk) command -v apk >/dev/null 2>&1 || PM="" ;;
    esac

    # Unbekannte Kennung oder Paketmanager fehlt: am vorhandenen festmachen.
    if [ -z "$PM" ]; then
        if command -v apt-get >/dev/null 2>&1; then PM="apt"
        elif command -v dnf >/dev/null 2>&1; then PM="dnf"
        elif command -v pacman >/dev/null 2>&1; then PM="pacman"
        elif command -v zypper >/dev/null 2>&1; then PM="zypper"
        elif command -v apk >/dev/null 2>&1; then PM="apk"
        fi
    fi
}

is_rhel_like() {
    [ "$PM" = "dnf" ] && [ "$OS_ID" != "fedora" ]
}

# ---------------------------------------------------------------------------
# Python

python_ok() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

python_version() {
    "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

# Sucht einen passenden Interpreter, bevorzugt den Standard der Distribution.
find_python() {
    PYTHON=""
    local candidate path
    if [ -n "$PYTHON_OVERRIDE" ]; then
        path="$(command -v -- "$PYTHON_OVERRIDE" 2>/dev/null || true)"
        [ -n "$path" ] || die "$EXIT_USAGE" "--python: ${PYTHON_OVERRIDE} nicht gefunden"
        python_ok "$path" || die "$EXIT_USAGE" "--python: ${PYTHON_OVERRIDE} ist älter als Python ${MIN_PYTHON}"
        PYTHON="$path"
        return 0
    fi
    if [ "$PM" = "apk" ]; then
        # PySide6 kommt unter Alpine aus py3-pyside6, das zum System-Python gehört.
        if [ -x /usr/bin/python3 ] && python_ok /usr/bin/python3; then
            PYTHON=/usr/bin/python3
        fi
        return 0
    fi
    for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
        path="$(command -v "$candidate" 2>/dev/null || true)"
        if [ -n "$path" ] && python_ok "$path"; then
            PYTHON="$path"
            return 0
        fi
    done
    return 0
}

# Gehört der Interpreter zur Distribution (und braucht deren -venv/-dev-Pakete)?
python_is_system() {
    case "$(readlink -f -- "$PYTHON")" in
        /usr/bin/*) return 0 ;;
        *) return 1 ;;
    esac
}

# Paketname, dem der Interpreter gehört (rpm-Distributionen).
rpm_python_package() {
    local name
    name="$(rpm -qf --qf '%{NAME}\n' -- "$(readlink -f -- "$PYTHON")" 2>/dev/null | head -n 1 || true)"
    case "$name" in
        ""|*"not owned"*) return 1 ;;
    esac
    printf '%s' "${name%-base}"
}

apt_candidate_version() {
    LC_ALL=C apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ { print $2; exit }'
}

version_at_least_311() {
    # $1 wie "3.12.3-1ubuntu1" oder "3.11"
    local v="${1#*:}" major minor
    major="${v%%.*}"
    v="${v#*.}"
    minor="${v%%[!0-9]*}"
    [[ "$major" =~ ^[0-9]+$ ]] && [[ "$minor" =~ ^[0-9]+$ ]] || return 1
    [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }
}

# Python-Pakete der Distribution, passend zum gefundenen Interpreter.
python_packages() {
    local v name major
    if [ -n "$PYTHON" ] && ! python_is_system; then
        return 0  # eigener Interpreter (pyenv, /usr/local, ...): keine Distributionspakete
    fi
    case "$PM" in
        apt)
            if [ -n "$PYTHON" ]; then
                v="$(python_version "$PYTHON")"
                printf '%s\n' "python${v}-venv" "python${v}-dev"
            else
                v="$(apt_candidate_version python3)"
                if [ -z "$v" ] || [ "$v" = "(none)" ] || version_at_least_311 "$v"; then
                    printf '%s\n' python3 python3-venv python3-dev
                else
                    printf '%s\n' python3.11 python3.11-venv python3.11-dev
                fi
            fi
            ;;
        dnf)
            if [ -n "$PYTHON" ] && name="$(rpm_python_package)"; then
                printf '%s\n' "$name" "${name}-devel"
            elif is_rhel_like; then
                major="${OS_VERSION%%.*}"
                if [[ "$major" =~ ^[0-9]+$ ]] && [ "$major" -lt 10 ]; then
                    printf '%s\n' python3.11 python3.11-devel
                else
                    printf '%s\n' python3 python3-devel
                fi
            else
                printf '%s\n' python3 python3-devel
            fi
            ;;
        zypper)
            if [ -n "$PYTHON" ] && name="$(rpm_python_package)"; then
                printf '%s\n' "$name" "${name}-devel"
            elif [ "${OS_VERSION%%.*}" = "15" ]; then
                printf '%s\n' python311 python311-devel
            else
                printf '%s\n' python3 python3-devel
            fi
            ;;
        pacman) printf '%s\n' python ;;
        apk) printf '%s\n' python3 python3-dev ;;
    esac
}

# ---------------------------------------------------------------------------
# Systempakete

# Alles, was die Loopstation zur Laufzeit braucht, plus das, was pip braucht,
# um python-rtmidi (und unter Alpine weitere Pakete) aus dem Quelltext zu bauen.
base_packages() {
    case "$PM" in
        apt)
            printf '%s\n' \
                build-essential pkg-config libasound2-dev \
                libportaudio2 libsndfile1 'libasound2t64|libasound2' \
                libgl1 libegl1 libopengl0 libfontconfig1 libfreetype6 libdbus-1-3 \
                'libglib2.0-0t64|libglib2.0-0' libxkbcommon0 libxkbcommon-x11-0 \
                libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
                libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
                libwayland-client0 libwayland-cursor0 libwayland-egl1 fonts-dejavu-core
            ;;
        dnf)
            printf '%s\n' \
                gcc gcc-c++ make pkgconf-pkg-config alsa-lib-devel \
                portaudio libsndfile alsa-lib \
                mesa-libGL mesa-libEGL libglvnd-opengl fontconfig freetype dbus-libs glib2 \
                libxkbcommon libxkbcommon-x11 libX11-xcb xcb-util-cursor xcb-util-wm \
                xcb-util-image xcb-util-keysyms xcb-util-renderutil \
                libwayland-client libwayland-cursor libwayland-egl dejavu-sans-fonts
            ;;
        pacman)
            printf '%s\n' \
                gcc make pkgconf \
                portaudio libsndfile alsa-lib \
                libglvnd fontconfig freetype2 dbus glib2 \
                libxkbcommon libxkbcommon-x11 libx11 xcb-util-cursor xcb-util-wm \
                xcb-util-image xcb-util-keysyms xcb-util-renderutil \
                wayland ttf-dejavu
            ;;
        zypper)
            printf '%s\n' \
                gcc gcc-c++ make pkg-config alsa-devel \
                libportaudio2 libsndfile1 libasound2 \
                Mesa-libGL1 Mesa-libEGL1 libglvnd fontconfig libfreetype6 libdbus-1-3 \
                libglib-2_0-0 libgthread-2_0-0 libxkbcommon0 libxkbcommon-x11-0 libX11-xcb1 libxcb-cursor0 \
                libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
                libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
                libwayland-client0 libwayland-cursor0 libwayland-egl1 dejavu-fonts
            ;;
        apk)
            printf '%s\n' \
                build-base pkgconf alsa-lib-dev \
                py3-pyside6 portaudio libsndfile alsa-lib \
                mesa-gl mesa-egl fontconfig freetype dbus-libs glib \
                libxkbcommon xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
                xcb-util-renderutil wayland-libs-client wayland-libs-cursor wayland-libs-egl \
                font-dejavu
            ;;
    esac
}

pkg_installed() {
    case "$PM" in
        apt)
            # shellcheck disable=SC2016 # dpkg-Formatfeld, keine Shell-Variable
            [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null || true)" = "installed" ]
            ;;
        dnf|zypper) rpm -q --whatprovides "$1" >/dev/null 2>&1 ;;
        pacman) pacman -T "$1" >/dev/null 2>&1 ;;
        apk) apk info -e "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

pkg_available() {
    case "$PM" in
        apt) apt-cache show --no-all-versions "$1" >/dev/null 2>&1 ;;
        dnf) dnf -q --cacheonly list --available "$1" >/dev/null 2>&1 \
                || dnf -q list --available "$1" >/dev/null 2>&1 ;;
        zypper) zypper --non-interactive --no-refresh search -x "$1" >/dev/null 2>&1 ;;
        pacman) pacman -Si "$1" >/dev/null 2>&1 ;;
        apk) [ -n "$(apk search -x "$1" 2>/dev/null)" ] ;;
        *) return 1 ;;
    esac
}

# Füllt PACKAGES und MISSING. Alternativen "a|b": installiert, wenn eine davon
# installiert ist; sonst wird die erste verfügbare genommen.
collect_packages() {
    local entry alt chosen found
    local -a alts
    PACKAGES=()
    MISSING=()
    while IFS= read -r entry; do
        [ -n "$entry" ] && PACKAGES+=("$entry")
    done < <(python_packages; base_packages)

    for entry in "${PACKAGES[@]}"; do
        found=0
        IFS='|' read -r -a alts <<<"$entry"
        for alt in "${alts[@]}"; do
            if pkg_installed "$alt"; then
                found=1
                break
            fi
        done
        [ "$found" -eq 1 ] && continue
        chosen=""
        if [ "${#alts[@]}" -gt 1 ]; then
            for alt in "${alts[@]}"; do
                if pkg_available "$alt"; then
                    chosen="$alt"
                    break
                fi
            done
        fi
        MISSING+=("${chosen:-${alts[0]}}")
    done
}

install_command() {
    case "$PM" in
        apt) printf '%s\n' apt-get install -y --no-install-recommends ;;
        dnf) printf '%s\n' dnf install -y ;;
        pacman)
            if pacman_sync_ready; then
                printf '%s\n' pacman -S --needed --noconfirm
            else
                printf '%s\n' pacman -Syu --needed --noconfirm
            fi
            ;;
        zypper) printf '%s\n' zypper --non-interactive install --no-recommends ;;
        apk) printf '%s\n' apk add ;;
    esac
}

pacman_sync_ready() {
    compgen -G '/var/lib/pacman/sync/*.db' >/dev/null
}

print_missing_help() {
    local cmd
    cmd="$(install_command | tr '\n' ' ')"
    printf '\nFolgende Systempakete fehlen noch:\n' >&2
    printf '    %s\n' "${MISSING[@]}" >&2
    printf '\nAls Administrator installieren, zum Beispiel:\n' >&2
    case "$PM" in
        apt) printf '    sudo apt-get update && sudo %s%s\n' "$cmd" "${MISSING[*]}" >&2 ;;
        *) printf '    sudo %s%s\n' "$cmd" "${MISSING[*]}" >&2 ;;
    esac
    if is_rhel_like; then
        printf '    (xcb-util-cursor und portaudio liegen unter RHEL-Abkömmlingen in EPEL: sudo dnf install epel-release)\n' >&2
    fi
    printf 'Danach dieses Skript erneut starten.\n' >&2
}

choose_root_cmd() {
    if [ "$(id -u)" -eq 0 ]; then
        ROOT_CMD=()
    elif command -v sudo >/dev/null 2>&1; then
        ROOT_CMD=(sudo)
    elif command -v doas >/dev/null 2>&1; then
        ROOT_CMD=(doas)
    else
        return 1
    fi
}

# Unter RHEL-Abkömmlingen liegen einige Pakete in EPEL und CRB.
enable_rhel_extras() {
    is_rhel_like || return 0
    local need=0 pkg
    for pkg in "${MISSING[@]}"; do
        case "$pkg" in
            xcb-util-cursor|portaudio) pkg_available "$pkg" || need=1 ;;
        esac
    done
    [ "$need" -eq 1 ] || return 0
    if ! pkg_installed epel-release; then
        step "EPEL einschalten (für xcb-util-cursor und portaudio)"
        run_root dnf install -y epel-release
    fi
    if command -v crb >/dev/null 2>&1; then
        run_root crb enable
    fi
}

install_system_packages() {
    step "Systempakete prüfen (${OS_NAME}, Paketmanager: ${PM})"
    collect_packages
    if [ "${#MISSING[@]}" -eq 0 ]; then
        ok "alle Systempakete sind vorhanden"
        return 0
    fi

    info "fehlend: ${MISSING[*]}"
    local cmd=()
    mapfile -t cmd < <(install_command)
    if [ "$DRY_RUN" -eq 1 ]; then
        if [ "$PM" = "apt" ]; then
            printf '    [Trockenlauf] %s\n' "$(quote_cmd sudo apt-get update)"
        fi
        printf '    [Trockenlauf] %s\n' "$(quote_cmd sudo "${cmd[@]}" "${MISSING[@]}")"
        return 0
    fi

    if ! choose_root_cmd; then
        warn "weder root noch sudo oder doas verfügbar"
        print_missing_help
        exit "$EXIT_PACKAGES"
    fi
    local who="mit ${ROOT_CMD[*]:-root-Rechten}"
    if [ "$PM" = "pacman" ] && ! pacman_sync_ready; then
        warn "die pacman-Paketdatenbanken fehlen: dafür ist ein vollständiges Systemupdate (pacman -Syu) nötig, das alle installierten Pakete aktualisiert"
    fi
    if ! confirm "Diese Pakete jetzt ${who} installieren?"; then
        print_missing_help
        exit "$EXIT_PACKAGES"
    fi

    # Paketquellen auffrischen, dann Alternativen neu auflösen.
    case "$PM" in
        apt)
            run_root apt-get update || { print_missing_help; die "$EXIT_PACKAGES" "apt-get update ist fehlgeschlagen"; }
            collect_packages
            ;;
        zypper)
            run_root zypper --non-interactive refresh || warn "zypper refresh ist fehlgeschlagen"
            ;;
        apk)
            run_root apk update || warn "apk update ist fehlgeschlagen"
            ;;
        dnf)
            enable_rhel_extras || warn "EPEL/CRB konnte nicht eingeschaltet werden"
            ;;
    esac

    if [ "${#MISSING[@]}" -gt 0 ]; then
        mapfile -t cmd < <(install_command)
        if [ "$PM" = "apt" ]; then
            run_root env DEBIAN_FRONTEND=noninteractive "${cmd[@]}" "${MISSING[@]}" \
                || { print_missing_help; die "$EXIT_PACKAGES" "Installation der Systempakete ist fehlgeschlagen"; }
        else
            run_root "${cmd[@]}" "${MISSING[@]}" \
                || { print_missing_help; die "$EXIT_PACKAGES" "Installation der Systempakete ist fehlgeschlagen"; }
        fi
    fi

    collect_packages
    if [ "${#MISSING[@]}" -gt 0 ]; then
        print_missing_help
        die "$EXIT_PACKAGES" "nach der Installation fehlen noch Pakete"
    fi
    ok "Systempakete installiert"
}

# ---------------------------------------------------------------------------
# Programm

ensure_python() {
    find_python
    if [ -z "$PYTHON" ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            info "Python ${MIN_PYTHON}+ wird mit den Systempaketen installiert"
            PYTHON="python3"
            return 0
        fi
        die "$EXIT_ERROR" "kein Python ${MIN_PYTHON} oder neuer gefunden. Bitte installieren (oder --python PFAD angeben) und erneut starten."
    fi
    ok "Python $(python_version "$PYTHON"): ${PYTHON}"
}

install_app() {
    local stamp venv_dir pip_python old_target=""
    stamp="$(date +%Y%m%d%H%M%S)"
    venv_dir="$APP_DIR/venv-$stamp"
    pip_python="$venv_dir/bin/python"

    step "Programm installieren nach ${APP_DIR}"
    run mkdir -p "$APP_DIR"

    local venv_args=()
    if [ "$PM" = "apk" ]; then
        venv_args+=(--system-site-packages)  # PySide6 aus py3-pyside6
    fi
    if [ "$DRY_RUN" -eq 0 ] && [ -e "$venv_dir" ]; then
        die "$EXIT_ERROR" "${venv_dir} gibt es schon; bitte eine Sekunde warten und erneut starten"
    fi

    # Neues venv neben dem alten bauen und erst nach erfolgreicher Prüfung
    # umschalten: ein abgebrochener Lauf lässt die alte Installation intakt.
    if ! run "$PYTHON" -m venv ${venv_args[@]+"${venv_args[@]}"} "$venv_dir"; then
        run rm -rf "$venv_dir"
        die "$EXIT_ERROR" "venv konnte nicht angelegt werden. Fehlt das venv-Modul (Debian/Ubuntu: Paket python3-venv)?"
    fi
    if ! run "$pip_python" -m pip install --disable-pip-version-check --upgrade pip \
        || ! run "$pip_python" -m pip install --disable-pip-version-check --upgrade "$REPO_DIR"; then
        run rm -rf "$venv_dir"
        die "$EXIT_ERROR" "pip konnte die Loopstation nicht installieren (Ausgabe oben). Internetverbindung prüfen; bei Compiler-Fehlern fehlen Systempakete."
    fi

    step "Installation prüfen"
    if ! run "$pip_python" -c 'import PySide6.QtWidgets, numpy, soundfile, mido, rtmidi, loopstation.app'; then
        run rm -rf "$venv_dir"
        die "$EXIT_ERROR" "die installierten Python-Module lassen sich nicht laden (Ausgabe oben)"
    fi
    if [ "$DRY_RUN" -eq 0 ] && ! "$pip_python" -c 'import sounddevice' >/dev/null 2>&1; then
        warn "PortAudio wurde nicht gefunden: die Loopstation startet, aber ohne Ton (Paket portaudio bzw. libportaudio2)"
    fi
    check_qt_libraries "$pip_python"

    if [ -L "$VENV_LINK" ]; then
        old_target="$(readlink -- "$VENV_LINK")"
    elif [ -e "$VENV_LINK" ]; then
        die "$EXIT_ERROR" "${VENV_LINK} ist kein Link dieses Skripts; bitte prüfen und entfernen"
    fi
    run ln -sfn "venv-$stamp" "$VENV_LINK"
    case "$old_target" in
        venv-[0-9]*)
            case "$old_target" in */*) old_target="" ;; esac
            ;;
        *) old_target="" ;;
    esac
    if [ -n "$old_target" ] && [ "$old_target" != "venv-$stamp" ]; then
        run rm -rf "${APP_DIR:?}/${old_target}"
    fi

    if [ ! -e "$APP_DIR/settings.toml" ]; then
        run cp "$REPO_DIR/settings.toml" "$APP_DIR/settings.toml"
    else
        info "vorhandene Einstellungen bleiben: ${APP_DIR}/settings.toml"
    fi
    [ "$DRY_RUN" -eq 1 ] || ok "Programm installiert"
}

# Fehlende Bibliotheken der Qt-Plattform-Plugins (xcb, wayland) melden.
check_qt_libraries() {
    local py="$1" plugins plugin missing
    [ "$DRY_RUN" -eq 0 ] || return 0
    command -v ldd >/dev/null 2>&1 || return 0
    plugins="$("$py" -c 'import os, PySide6; from PySide6.QtCore import QLibraryInfo; print(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))' 2>/dev/null || true)"
    [ -d "$plugins/platforms" ] || return 0
    for plugin in "$plugins"/platforms/libqxcb.so "$plugins"/platforms/libqwayland*.so; do
        [ -f "$plugin" ] || continue
        missing="$(ldd "$plugin" 2>/dev/null | awk '/not found/ { print $1 }' | sort -u | tr '\n' ' ')"
        if [ -n "$missing" ]; then
            warn "Qt-Plugin $(basename -- "$plugin") findet nicht: ${missing}"
        fi
    done
}

install_launcher() {
    step "Startbefehl, Menüeintrag und Icon"
    run mkdir -p "$BIN_DIR" "$(dirname -- "$DESKTOP_FILE")" "$(dirname -- "$ICON_FILE")"

    if [ -e "$LAUNCHER" ] && ! grep -qF "$MARKER" "$LAUNCHER" 2>/dev/null; then
        die "$EXIT_ERROR" "${LAUNCHER} gibt es schon und stammt nicht von diesem Skript; bitte prüfen und entfernen"
    fi

    local launcher_text desktop_text write_desktop=1
    launcher_text="#!/bin/sh
${MARKER}
# Startet die ${APP_NAME}. Einstellungen, Aufnahmen und Protokoll liegen in APP_DIR.
APP_DIR=$(sh_quote "$APP_DIR")
cd \"\$APP_DIR\" || exit 1
exec \"\$APP_DIR/venv/bin/python\" -m loopstation \"\$@\"
"
    # Im Exec-Feld des Menüeintrags sind Leerzeichen in Anführungszeichen
    # erlaubt; Zeichen mit Sonderbedeutung (" ` $ \ %) kommen in einem
    # Benutzerpfad praktisch nie vor und werden nicht maskiert, sondern gemeldet.
    if [[ "$LAUNCHER" == *[\"\`\$\\%]* ]]; then
        warn "der Pfad ${LAUNCHER} enthält Sonderzeichen; der Menüeintrag wird nicht angelegt"
        write_desktop=0
    fi
    desktop_text="[Desktop Entry]
${MARKER}
Type=Application
Name=${APP_NAME}
GenericName=Loopstation für Kinder
Comment=Geräusche aufnehmen, abspielen und als Loop laufen lassen
Exec=\"${LAUNCHER}\"
Icon=${APP_ID}
Terminal=false
Categories=AudioVideo;Audio;Education;
Keywords=Loop;Musik;Aufnahme;Launchpad;
"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '    [Trockenlauf] Startbefehl schreiben: %s\n' "$LAUNCHER"
        printf '    [Trockenlauf] Menüeintrag schreiben: %s\n' "$DESKTOP_FILE"
        printf '    [Trockenlauf] Icon kopieren: %s\n' "$ICON_FILE"
    else
        printf '%s' "$launcher_text" >"$LAUNCHER.tmp"
        chmod 755 "$LAUNCHER.tmp"
        mv -f "$LAUNCHER.tmp" "$LAUNCHER"
        if [ "$write_desktop" -eq 1 ]; then
            printf '%s' "$desktop_text" >"$DESKTOP_FILE"
        fi
        cp "$REPO_DIR/packaging/linux/$APP_ID.svg" "$ICON_FILE"
        refresh_desktop_caches
    fi
    [ "$DRY_RUN" -eq 1 ] || ok "Startbefehl: ${LAUNCHER}"
}

refresh_desktop_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "$(dirname -- "$DESKTOP_FILE")" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$DATA_HOME/icons/hicolor/index.theme" ]; then
        gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

audio_hints() {
    if ! command -v pipewire >/dev/null 2>&1 && ! command -v pulseaudio >/dev/null 2>&1 \
        && ! command -v pactl >/dev/null 2>&1; then
        warn "kein PipeWire oder PulseAudio gefunden. Der Ton läuft dann direkt über ALSA;" \
            "auf einem Desktop ist meist einer der beiden Audio-Server dabei (Paket pipewire-pulse oder pulseaudio)."
    fi
    if [ -d /dev/snd ] && [ ! -e /dev/snd/seq ]; then
        warn "/dev/snd/seq fehlt: für das Launchpad das Kernelmodul snd-seq laden (sudo modprobe snd-seq)"
    fi
}

path_hint() {
    case ":${PATH:-}:" in
        *":$BIN_DIR:"*) ;;
        *) warn "${BIN_DIR} ist nicht im PATH. Start mit vollem Pfad (${LAUNCHER}) oder über das Menü;" \
                "dauerhaft: export PATH=\"\$HOME/.local/bin:\$PATH\" in ~/.profile" ;;
    esac
}

do_install() {
    check_source
    detect_distro
    find_python
    if [ "$SKIP_SYSTEM" -eq 1 ]; then
        step "Systempakete werden übersprungen (--no-system-packages)"
    elif [ -z "$PM" ]; then
        warn "Distribution ${OS_NAME} wird nicht erkannt; Systempakete bitte selbst installieren:" \
            "Python ${MIN_PYTHON}+ mit venv und Headern, C/C++-Compiler, pkg-config, PortAudio, libsndfile," \
            "ALSA (mit Headern), libGL/libEGL, libxkbcommon(-x11), xcb-util-cursor und die übrigen xcb-util-Bibliotheken, fontconfig."
        if [ "$DRY_RUN" -eq 0 ] && ! confirm "Ohne Systempakete weitermachen?"; then
            die "$EXIT_PACKAGES" "abgebrochen; mit --no-system-packages ohne Rückfrage weitermachen"
        fi
    else
        install_system_packages
    fi
    ensure_python
    install_app
    install_launcher
    audio_hints
    path_hint
    printf '\n'
    if [ "$DRY_RUN" -eq 1 ]; then
        ok "Trockenlauf beendet, nichts wurde verändert"
    else
        ok "Fertig. Starten mit: ${APP_ID}  (oder im Menü: ${APP_NAME})"
        info "Einstellungen: ${APP_DIR}/settings.toml"
        info "Deinstallieren: $0 --uninstall"
    fi
}

# ---------------------------------------------------------------------------
# Deinstallation

remove_if_ours() {
    local path="$1"
    [ -e "$path" ] || [ -L "$path" ] || return 0
    if grep -qF "$MARKER" "$path" 2>/dev/null; then
        run rm -f "$path"
        info "entfernt: ${path}"
    else
        warn "${path} stammt nicht von diesem Skript und bleibt liegen"
    fi
}

do_uninstall() {
    step "${APP_NAME} deinstallieren"
    remove_if_ours "$LAUNCHER"
    remove_if_ours "$DESKTOP_FILE"
    if [ -f "$ICON_FILE" ]; then
        run rm -f "$ICON_FILE"
        info "entfernt: ${ICON_FILE}"
    fi

    local found=0 dir
    if [ -d "$APP_DIR" ]; then
        for dir in "$APP_DIR"/venv-* "$VENV_LINK"; do
            if [ -e "$dir" ] || [ -L "$dir" ]; then
                run rm -rf "$dir"
                found=1
            fi
        done
    fi
    if [ "$found" -eq 1 ]; then
        info "entfernt: Programm (venv) in ${APP_DIR}"
    fi

    if [ "$DRY_RUN" -eq 0 ]; then
        refresh_desktop_caches
    fi

    if [ "$PURGE" -eq 1 ] && [ -d "$APP_DIR" ]; then
        warn "--purge löscht alle Aufnahmen, das Protokoll und die Einstellungen in ${APP_DIR}"
        if [ "$DRY_RUN" -eq 1 ]; then
            run rm -rf "$APP_DIR"
        elif confirm "Wirklich alles in ${APP_DIR} löschen?"; then
            run rm -rf "$APP_DIR"
            info "entfernt: ${APP_DIR}"
        else
            info "Aufnahmen und Einstellungen bleiben in ${APP_DIR}"
        fi
    elif [ -d "$APP_DIR" ]; then
        info "Aufnahmen und Einstellungen bleiben in ${APP_DIR} (löschen mit --uninstall --purge)"
    fi
    info "Systempakete bleiben installiert, weil andere Programme sie mitbenutzen können."
    if [ "$DRY_RUN" -eq 1 ]; then
        ok "Trockenlauf beendet, nichts wurde verändert"
    else
        ok "deinstalliert"
    fi
}

main() {
    parse_args "$@"
    check_platform
    check_tools
    init_paths
    if [ "$DRY_RUN" -eq 1 ]; then
        step "Trockenlauf: es wird nichts verändert"
    fi
    if [ "$UNINSTALL" -eq 1 ]; then
        do_uninstall
    else
        do_install
    fi
}

main "$@"
