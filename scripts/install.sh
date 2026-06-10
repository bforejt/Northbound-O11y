#!/usr/bin/env bash
# Fresh-host bootstrap for the Northbound observability stack.
# Debian/Ubuntu: installs Docker Engine + compose plugin from Docker's apt repo.
# macOS: verifies Docker Desktop. WSL2: same as Debian/Ubuntu (systemd optional).
# Usage: scripts/install.sh [--systemd]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WANT_SYSTEMD=no
[ "${1:-}" = "--systemd" ] && WANT_SYSTEMD=yes

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "not root and sudo not found"
    SUDO="sudo"
fi

install_docker_debian() {
    say "Installing Docker Engine from download.docker.com..."
    . /etc/os-release
    repo_os="$ID"   # ubuntu or debian
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq ca-certificates curl gnupg
    $SUDO install -m 0755 -d /etc/apt/keyrings
    $SUDO curl -fsSL "https://download.docker.com/linux/$repo_os/gpg" -o /etc/apt/keyrings/docker.asc
    $SUDO chmod a+r /etc/apt/keyrings/docker.asc
    arch=$(dpkg --print-architecture)
    codename="${VERSION_CODENAME:-$(. /etc/os-release && echo "$VERSION_CODENAME")}"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
        "$arch" "$repo_os" "$codename" | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

case "$(uname -s)" in
    Darwin)
        say "macOS detected."
        if ! command -v docker >/dev/null 2>&1; then
            die "Docker Desktop is not installed. Install it from https://docs.docker.com/desktop/setup/install/mac-install/ then re-run."
        fi
        docker info >/dev/null 2>&1 || die "Docker Desktop is installed but not running -- start it (open -a Docker) and re-run."
        say "Docker Desktop is running."
        [ "$WANT_SYSTEMD" = "yes" ] && say "NOTE: --systemd is ignored on macOS."
        ;;
    Linux)
        if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
            say "Docker is already installed and running."
        else
            . /etc/os-release
            case "${ID:-} ${ID_LIKE:-}" in
                *debian*|*ubuntu*) install_docker_debian ;;
                *) die "unsupported distro '${ID:-unknown}' -- install Docker Engine + compose plugin manually, then re-run" ;;
            esac
            if [ -d /run/systemd/system ]; then
                $SUDO systemctl enable --now docker
            else
                say "NOTE: no systemd (WSL without systemd?) -- start dockerd yourself or enable systemd in /etc/wsl.conf."
            fi
        fi

        target_user="${SUDO_USER:-$USER}"
        if [ "$target_user" != "root" ] && ! id -nG "$target_user" | tr ' ' '\n' | grep -qx docker; then
            $SUDO usermod -aG docker "$target_user"
            say "Added $target_user to the docker group -- log out and back in for it to apply."
        fi

        if [ "$WANT_SYSTEMD" = "yes" ]; then
            if [ -d /run/systemd/system ]; then
                say "Installing systemd unit northbound-o11y.service..."
                sed "s|__REPO_DIR__|$ROOT|" "$ROOT/scripts/northbound-o11y.service" \
                    | $SUDO tee /etc/systemd/system/northbound-o11y.service >/dev/null
                $SUDO systemctl daemon-reload
                $SUDO systemctl enable northbound-o11y.service
                say "Enabled. The stack will start on boot (uses docker compose up -d in $ROOT)."
            else
                say "NOTE: --systemd requested but no systemd available -- skipped."
            fi
        fi
        ;;
    *)
        die "unsupported OS $(uname -s) -- supported: Debian/Ubuntu, macOS, WSL2"
        ;;
esac

docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin missing after install"

say ""
say "Bootstrap complete. Next:"
say "  ./o11y init    # create .env"
say "  ./o11y up      # start the stack"
say "  ./o11y status  # verify"
