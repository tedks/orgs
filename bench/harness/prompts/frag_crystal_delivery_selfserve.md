**This run has no standup bus, so nothing will push a conflict to you.**
Run the check yourself when you want it, after your workers have committed:

```bash
{{CRYSTAL}} --base {{RUN_BRANCH}} --test-cmd '{{CRYSTAL_TEST_CMD}}' <worker branches>
```

It exits 0 clean, 1 conflicts found, 2 error.
