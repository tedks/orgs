{
  description = "Portable agent skills and the harness-control runtime";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

  outputs = { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      lib = pkgs.lib;
      python = pkgs.python312;
      pythonPackages = pkgs.python312Packages;
      mcp = pythonPackages.mcp;
      packageVersion = (builtins.fromTOML (builtins.readFile ./harness-control/pyproject.toml)).project.version;
      runtimeSkillsFiles = lib.fileset.toSource {
        root = ./.;
        fileset = lib.fileset.unions [
          ./skills/_shared
          ./skills/spawn-agent/scripts/claude-send-screen.py
          ./skills/spawn-agent/scripts/tmux-ctx.sh
          ./skills/spawn-agent/scripts/tmux-message.py
          ./skills/spawn-agent/scripts/tmux-message.sh
          ./skills/spawn-agent/scripts/tmux-resolve.sh
        ];
      };
      nativeTestsSource = lib.fileset.toSource {
        root = ./.;
        fileset = lib.fileset.unions [
          ./skills/_shared/agent_skills_config.py
          ./skills/_shared/native
          ./skills/retire-agent
          ./tests/test_native_helpers.py
        ];
      };
      harnessControlLibrary = pythonPackages.buildPythonPackage {
        pname = "agent-harness-control";
        version = packageVersion;
        pyproject = true;
        src = ./harness-control;

        build-system = [ pythonPackages.setuptools ];
        dependencies = [ mcp ];
        doCheck = false;
      };
      runtimePython = python.withPackages (_: [ harnessControlLibrary ]);
      runtimeInputs = [ runtimePython pkgs.bash pkgs.coreutils pkgs.gitMinimal ];
      runtimePath = lib.makeBinPath runtimeInputs;
      runtimeSkillsSource = pkgs.runCommand "harness-control-skills" {
        nativeBuildInputs = runtimeInputs;
      } ''
        mkdir -p "$out"
        cp -R ${runtimeSkillsFiles}/skills "$out/skills"
        chmod -R u+w "$out/skills"
        patchShebangs --build "$out/skills/spawn-agent/scripts"
      '';
      harnessControl = pkgs.writeShellApplication {
        name = "harness-control";
        text = ''
          export PATH=${runtimePath}''${PATH:+:$PATH}
          for variable in ''${!PYTHON@}; do
            unset "$variable"
          done
          unset NIX_PYTHONPATH
          export AGENT_SKILLS_ROOT=${runtimeSkillsSource}/skills
          export PYTHONDONTWRITEBYTECODE=1
          export PYTHONNOUSERSITE=1
          exec ${runtimePython}/bin/python3 -I -m server "$@"
        '';
        meta = {
          description = "Pinned self-status and lifecycle MCP server for terminal agents";
          license = lib.licenses.agpl3Only;
          mainProgram = "harness-control";
          platforms = [ system ];
        };
      };
    in
    assert lib.versionAtLeast mcp.version "1.2.0";
    assert lib.versionOlder mcp.version "2";
    {
      packages.${system} = {
        harness-control = harnessControl;
        default = harnessControl;
      };

      apps.${system} = {
        harness-control = {
          type = "app";
          program = lib.getExe harnessControl;
          meta.description = "Run the packaged harness-control MCP server";
        };
        default = {
          type = "app";
          program = lib.getExe harnessControl;
          meta.description = "Run the packaged harness-control MCP server";
        };
      };

      checks.${system} = {
        harness-control-unit = pkgs.runCommand "harness-control-unit" {
          nativeBuildInputs = [ runtimePython ];
        } ''
          export AGENT_SKILLS_ROOT=${runtimeSkillsSource}/skills
          export HARNESS_TEST_SLEEP=${lib.getExe' pkgs.coreutils "sleep"}
          export PYTHONDONTWRITEBYTECODE=1
          export PYTHONPATH=${./harness-control}
          export PATH=${runtimePath}:${lib.getBin pkgs.tmux}/bin
          cp -R ${nativeTestsSource} "$TMPDIR/native-tests"
          chmod -R u+w "$TMPDIR/native-tests"
          native_tests="$TMPDIR/native-tests"
          ${runtimePython}/bin/python3 ${./harness-control}/test_session_id.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_tools.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_lifecycle.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_runtime.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_control_core.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_status_live.py
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_tools.py --mutation-check
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_lifecycle.py --mutation-check
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_control_core.py --mutation-check
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_status_live.py --mutation-check
          ${runtimePython}/bin/python3 ${./harness-control}/test_harness_control_core.py --live-integration
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-harness-identity.py"
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-harness-identity.py" --mutation-check
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-session-binding.py"
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-session-binding.py" --mutation-check
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-codex-status.py"
          ${runtimePython}/bin/python3 "$native_tests/skills/_shared/native/tests/test-codex-status.py" --mutation-check
          ${runtimePython}/bin/python3 "$native_tests/tests/test_native_helpers.py"
          ${runtimePython}/bin/python3 "$native_tests/tests/test_native_helpers.py" --mutation-check
          touch $out
        '';

        harness-control-package = pkgs.runCommand "harness-control-package" {
          nativeBuildInputs = [ runtimePython ];
        } ''
          ${runtimePython}/bin/python3 ${./harness-control}/test_package.py \
            ${lib.getExe harnessControl} ${./harness-control}
          set +e
          observer_error=$(AGENT_SKILLS_ROOT=${runtimeSkillsSource}/skills \
            ${runtimePython}/bin/python3 -E -s \
            ${harnessControlLibrary}/${python.sitePackages}/harness_control.py \
            --observe "$TMPDIR/observer" invalid 2>&1)
          observer_status=$?
          set -e
          test "$observer_status" -eq 1
          [[ "$observer_error" == *invalid_operation_id* ]]
          touch $out
        '';

        harness-control-transport = pkgs.runCommand "harness-control-transport" {
          nativeBuildInputs = [ runtimePython pkgs.bash pkgs.coreutils pkgs.tmux ];
        } ''
          socket="$TMPDIR/tmux-server"
          ${lib.getExe pkgs.tmux} -S "$socket" new-session -d -s harness-test \
            "${lib.getExe pkgs.bash} -c 'printf \"transport-ready\\n\"; exec ${lib.getExe' pkgs.coreutils "sleep"} 30'"
          pane=$(${lib.getExe pkgs.tmux} -S "$socket" display-message -p -t '=harness-test:0.0' '#{pane_id}')
          output=""
          for attempt in {1..50}; do
            output=$(AGENT_SKILLS_ROOT=${runtimeSkillsSource}/skills \
              SPAWN_TMUX_SOCKET="$socket" \
              ${runtimeSkillsSource}/skills/spawn-agent/scripts/tmux-message.sh read "$pane" || true)
            [[ "$output" == *transport-ready* ]] && break
            ${lib.getExe' pkgs.coreutils "sleep"} 0.1
          done
          [[ "$output" == *transport-ready* ]]
          ${lib.getExe pkgs.tmux} -S "$socket" kill-server
          touch $out
        '';
      };
    };
}
