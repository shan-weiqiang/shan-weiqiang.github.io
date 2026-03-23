# Linux shared libraries: link time vs load time, SONAME, RPATH, and naming

## 1. Link time vs load time

| | **Link time** (`ld` / `g++` at build) | **Load time** (`ld.so` at run) |
|---|----------------------------------------|--------------------------------|
| **What happens** | Resolves symbols, records **`DT_NEEDED`** entries (dependency names), may embed **`RPATH`/`RUNPATH`**. | Loads `.so` files into the process, resolves **`NEEDED`** to actual files on disk. |
| **What is stored** | Usually **SONAME strings** (e.g. `libfoo.so.3`), not full paths — plus optional **RPATH/RUNPATH**. | Uses **RPATH/RUNPATH**, **`LD_LIBRARY_PATH`**, **`ld.so.cache`**, default dirs to find files. |
| **Why they differ** | The linker picks one file per `-l` / `-L` order. | The loader may find a **different path** with the **same SONAME** — behavior is still OK if ABI matches. |

So “linked against X” and “loaded from path Y” are **related by SONAME and ABI**, not by identical file paths.

**RPATH vs RUNPATH quick note:**
- `RUNPATH` (newer, `DT_RUNPATH`) is generally preferred in modern toolchains and is intended to be overridable by `LD_LIBRARY_PATH`.
- `RPATH` (legacy, `DT_RPATH`) can be consulted earlier and can affect transitive lookup behavior differently in some dependency chains.

---

## 2. `DT_NEEDED`, SONAME, RPATH/RUNPATH resolution, and `$ORIGIN`

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
- `DT_RPATH` and `DT_RUNPATH` differ mainly in **precedence** and **transitive lookup behavior**; `RUNPATH` is newer and generally preferred for override flexibility.

### Typical resolution order (glibc `ld.so`, simplified; nuanced)

1. If **loading object has no RUNPATH**: consult its **RPATH chain** (loading object RPATH, then loader's RPATH up the chain, with RUNPATH boundaries).
2. **`LD_LIBRARY_PATH`** (unless ignored by secure-execution mode such as setuid/setgid).
3. **RUNPATH** of the loading object.
4. **`/etc/ld.so.cache`**.
5. Default directories (`/lib`, `/usr/lib`, ...).

```
Unless loading object has RUNPATH:
    RPATH of the loading object,
        then the RPATH of its loader (unless it has a RUNPATH), ...,
        until the end of the chain, which is either the executable
        or an object loaded by dlopen
    Unless executable has RUNPATH:
        RPATH of the executable
LD_LIBRARY_PATH
RUNPATH of the loading object
ld.so.cache
default dirs
```



In modern Linux practice, `RPATH` is generally considered legacy/deprecated in favor of `RUNPATH`.
Recommended approach: use `RUNPATH` for bundled defaults, and use `LD_LIBRARY_PATH` when you need to override which concrete library build is loaded at runtime.

So `RUNPATH` is typically after `LD_LIBRARY_PATH`, while legacy `RPATH` can be consulted earlier when `RUNPATH` is absent on the loading path.

Reference: [Stack Overflow discussion: use RPATH but not RUNPATH?](https://stackoverflow.com/questions/7967848/use-rpath-but-not-runpath)


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

---
