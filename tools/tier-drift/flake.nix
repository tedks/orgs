{
  description = "tier-drift: track how the model tier your agent work needs drifts over time";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachSystem [ "x86_64-linux" "aarch64-linux" ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.uv
            pkgs.ruff
            pkgs.bazel_7
            # Deliberately no openssh: collection must use the operator's own
            # ssh and config. A pinned newer OpenSSH (10.x) refuses configs
            # reached through a group-writable path that an older system ssh
            # accepts, which silently breaks remote collection in this shell.
          ];
          shellHook = ''
            echo "tier-drift dev shell: $(python --version) · uv $(uv --version | cut -d' ' -f2) · $(bazel --version)"
          '';
        };
      });
}
