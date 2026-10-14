# Playwright-on-Nix snippet for flake.nix dev shells.
#
# This is a SNIPPET, not a standalone flake: splice the pieces below into an
# existing devShell. It keeps Playwright browsers in the nix store so the npm
# @playwright/test package never downloads its own (unpatched, non-FHS-hostile)
# binaries.
#
# The nixpkgs playwright-driver version must match the npm @playwright/test
# version (check package.json), or the npm side will refuse the browsers.
{
  # 1. Add the browsers package to the dev shell:
  buildInputs = [
    # End-to-end browser tests (Playwright). Browsers live in the
    # nix store; the npm @playwright/test package is told to use
    # them via PLAYWRIGHT_BROWSERS_PATH below. Pinned via nixpkgs
    # so the npm side must match.
    pkgs.playwright-driver.browsers
  ];

  # 2. Export the environment in the shellHook (or as devShell attrs):
  shellHook = ''
    # Point Playwright at nix-store browsers and skip its host
    # validation (we're not on a stock Ubuntu, the browsers are
    # already patched for non-FHS systems).
    export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
    export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true
    export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=true

    # Optional (used by power): pin chromium to the nixpkgs binary
    # instead of the playwright-driver bundle. The two leading single-quotes
    # in the escape below keep Nix from interpolating (and pulling chromium
    # into the closure) while the line is commented out; drop them when
    # enabling it.
    # export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="''${pkgs.chromium}/bin/chromium"

    echo "  playwright: ${pkgs.playwright-driver.version} (browsers pinned via nix)"
  '';
}
