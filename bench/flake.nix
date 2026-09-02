{
  description = "orgs benchmark eval devshell — real graders and target deps";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in {
      # `nix develop ./bench` gives the eval environment: redis-cli (the
      # frozen RESP exam's external grader) plus python3. Add a target's
      # real client/conformance dependency here as new targets land, so the
      # frozen exam always runs against the real thing rather than a
      # self-authored stand-in.
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.redis pkgs.python3 ];
          shellHook = ''
            echo "orgs bench devshell: redis-cli $(redis-cli --version | cut -d' ' -f1-2), $(python3 --version)"
          '';
        };
      });
    };
}
