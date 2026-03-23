# Linux shared libraries: link time vs load time, SONAME, RPATH, and naming

## 1. Link time vs load time

| | **Link time** (`ld` / `g++` at build) | **Load time** (`ld.so` at run) |
|---|----------------------------------------|--------------------------------|
| **What happens** | Resolves symbols, records **`DT_NEEDED`** entries (dependency names), may embed **`RPATH`/`RUNPATH`**. | Loads `.so` files into the process, resolves **`NEEDED`** to actual files on disk. |
| **What is stored** | Usually **SONAME strings** (e.g. `libfoo.so.3`), not full paths — plus optional **RUNPATH**. | Uses **RUNPATH/RPATH**, **`LD_LIBRARY_PATH`**, **`ld.so.cache`**, default dirs to find files. |
| **Why they differ** | The linker picks one file per `-l` / `-L` order. | The loader may find a **different path** with the **same SONAME** — behavior is still OK if ABI matches. |

So “linked against X” and “loaded from path Y” are **related by SONAME and ABI**, not by identical file paths.

---

## 2. `DT_NEEDED`, SONAME, RPATH, resolution order, and `$ORIGIN`

### `DT_NEEDED` (the “NEEDED” section)

- Each dependency is recorded as a **string**, almost always the **SONAME** (e.g. `libgrpc.so.10`, `libz.so.1`).
- It is **not** a full path like `/usr/lib/x86_64-linux-gnu/libz.so.1`.

### SONAME

- Embedded in the **shared library** and used as the **key** for loading.
- **Same SONAME** ⇒ same **ABI family** (by project policy): old binaries should keep working with newer minors that keep that SONAME.

### `RPATH` / `RUNPATH`

- Embedded in the executable or `.so`: **extra directories** for the loader to search for **`NEEDED`** libraries.
- **`$ORIGIN`** expands to the **directory of the current binary or `.so`**, so you can use **paths relative to the installed file**, e.g. `$ORIGIN/../lib`.
- In CMake, **`$ORIGIN`** is often written as **`\$ORIGIN`** so CMake does not treat it as a variable.

### Typical resolution order (glibc `ld.so`, simplified)

1. **`LD_LIBRARY_PATH`** (if allowed for the process)
2. **`RUNPATH`** / **`RPATH`** on the **loading** object (executable or the `.so` requesting the load)
3. **`/etc/ld.so.cache`** (system defaults: `/lib`, `/usr/lib`, …)

So **RUNPATH** is usually **before** default system paths, but **after** **`LD_LIBRARY_PATH`** in common setups.


---

## 3. Linux shared library naming (real name, SONAME, linker name)

Three related names:

| Role | Example | Meaning |
|------|---------|--------|
| **Real name** | `libfoo.so.3.2.1` | Actual file on disk: **major.minor.patch** (or similar). |
| **SONAME** | `libfoo.so.3` | **ABI / major** line: recorded in **`DT_NEEDED`**, must stay stable for compatible upgrades. |
| **Linker name** | `libfoo.so` | Symlink for **compile-time** `-lfoo`; points at current dev/SONAME target. |

**Version digits (typical convention):**

- **First number (SONAME major, e.g. `3`)** — **incompatible ABI** change ⇒ new SONAME (e.g. `libfoo.so.4`). Old programs linked to `libfoo.so.3` do **not** use `libfoo.so.4` automatically.
- **Minor / patch (e.g. `2`, `1`)** — **within** the same SONAME: **backward compatible** changes (new symbols allowed in minor; patch = bugfix). SONAME often stays **`libfoo.so.3`**.

---

## 4. Why “exact file match” at link/load time vs why naming convention is enough

### Same process, same SONAME → one loaded library

- **`DT_NEEDED`** only names **`liba.so.3`**, not `3.1` vs `3.2`.
- The loader maps **one** `liba.so.3` into the process; **all** dependents share it.
- **Example:** if two dependent libraries were linked at build time against `a.3.1` and `a.3.2`, at runtime one process still usually loads only one `liba.so.3` implementation. So at least one side may not get the exact patch/minor file it saw at link time. This is exactly why the SONAME convention exists: `a.3.1` and `a.3.2` (same SONAME family `liba.so.3`) are expected to be interchangeable for existing ABI usage.
- **Convention:** any installed **`liba.so.3.x.y`** with SONAME **`liba.so.3`** must be **ABI-compatible** for symbols that older clients use; **newer** minor usually works for **older** binaries; **older** minor may miss **new** symbols required by something built against a **newer** minor (edge case).

### Why people still “pin” one directory (exact tree / RPATH)

- **SONAME** does not say **which build** (vendor patch, security fix, bug).
- Two paths with the **same SONAME** can still differ in **behavior** while staying ABI-compatible in theory.
- **Pinning** (one prefix, **`RUNPATH`**, one zlib tree) gives **reproducibility** and avoids picking the wrong copy.

### Summary

- **Naming / SONAME** = **ABI contract** and **which `.so` family** loads.
- **Exact path / one tree** = **which concrete build** you trust — **orthogonal** but **practically important** for a controlled product.

---
