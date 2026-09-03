**Nothing will push a conflict to you on this run.** Run the check yourself
when you want it, after your workers have committed:

```bash
{{CRYSTAL}} --base {{RUN_BRANCH}} --test-cmd '{{CRYSTAL_TEST_CMD}}' <worker branches>
```

It exits 0 clean, 1 conflicts found, 2 error.
