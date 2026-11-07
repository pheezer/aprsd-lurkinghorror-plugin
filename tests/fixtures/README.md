# Test fixtures

The engine and plugin tests need a Z-machine story file here named
`lurkinghorror.z3` (Z-machine version 3).

That file is a copyrighted Infocom game and is **not** redistributable, so it is
git-ignored and never committed. Supply your own legally-obtained copy:

```
cp /path/to/your/lurkinghorror.z3 tests/fixtures/lurkinghorror.z3
```

Tests that require it are skipped automatically when the file is absent, so the
rest of the suite (chunker, session store) still runs without it.
