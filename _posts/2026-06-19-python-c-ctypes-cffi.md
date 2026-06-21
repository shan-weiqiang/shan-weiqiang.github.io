---
layout: post
title:  "Python C Extensions: Part III — ctypes and CFFI"
date:   2026-06-19 18:22:46 +0800
tags: [python]
---

* toc
{:toc}

This article is Part III of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) covers hand-written extension functions and `PyTypeObject` binding. [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) covers bytecode, `tp_call`, and how C extension methods run without a nested eval loop. [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) covers compile-time C++ bindings as an alternative to both hand-written extensions and runtime FFI.

Part III covers **FFI** (foreign function interface): calling existing C libraries from Python with **ctypes** (stdlib) or **CFFI** (third-party), instead of writing a new `PyInit_*` module for every library.

The [ctypes documentation](https://docs.python.org/3/library/ctypes.html) recommends this path when your goal is calling C library functions or system calls — it is often more portable across Python implementations than compiling a custom C extension. That does **not** replace Part I’s `Config` / capsule patterns when you need full Python types and attribute integration.

Runnable demos live in the [python](https://github.com/shan-weiqiang/python) repository. Build the shared library once, then run each test:

```bash
make -C c_ext_ffi_clib
python3 c_ext_ctypes_add/test_ctypes_add.py
python3 c_ext_cffi_abi/test_cffi_abi.py
python3 c_ext_cffi_api/test_cffi_api.py
```

| Section | Demo folder |
|---|---|
| §7.2 | [c_ext_ctypes_add](https://github.com/shan-weiqiang/python/tree/main/c_ext_ctypes_add) (+ [c_ext_ffi_clib](https://github.com/shan-weiqiang/python/tree/main/c_ext_ffi_clib)) |
| §7.3 ABI | [c_ext_cffi_abi](https://github.com/shan-weiqiang/python/tree/main/c_ext_cffi_abi) |
| §7.3 API | [c_ext_cffi_api](https://github.com/shan-weiqiang/python/tree/main/c_ext_cffi_api) |
| §7.4 contrast | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) (Part I hand-written `Config`) |
| §7.4 contrast (pybind11) | [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) (Part VII) |

---

## Section 7: FFI vs Hand-Written C Extensions

**Hand-written extension (Part I):** you compile `mymodule.cpython-312-….so` that links against `libpython`. Import runs `PyInit_mymodule`; your C code calls library functions with normal compiler-generated calls and uses the Python C API (`PyArg_ParseTuple`, `PyTypeObject`, …) for Python integration.

**FFI (ctypes / CFFI):** you load an **existing** plain C shared library (`libadd.so` — no `Python.h`) at runtime. A **stdlib or pip-provided** C extension (`_ctypes` or `_cffi_backend`) marshals Python values and invokes the C function through **libffi**.

On Linux with CPython 3.12 you will not find `_ctypes` as `/usr/lib/python3.12/_ctypes`. It is a versioned extension module:

```python
import _ctypes
print(_ctypes.__file__)
# e.g. /usr/lib/python3.12/lib-dynload/_ctypes.cpython-312-aarch64-linux-gnu.so
```

Both FFI backends link libffi:

```text
$ ldd .../_ctypes.cpython-312-aarch64-linux-gnu.so
    libffi.so.8 => /lib/aarch64-linux-gnu/libffi.so.8

$ ldd .../_cffi_backend.cpython-312-aarch64-linux-gnu.so
    libffi.so.8 => /lib/aarch64-linux-gnu/libffi.so.8
```

Your target library (`libadd.so`) does **not** need libffi — only the FFI machinery does.

![ctypes call flow from Python through _ctypes and libffi to libadd.so](/assets/images/python_c_ext_ctypes_call_flow.png)

---

### 7.1 What libffi Does

When you compile C normally, the compiler knows each function’s signature and emits a fixed call. **libffi** solves the opposite problem at **runtime**: given a **function pointer** and a **type description**, it places arguments in the correct registers/stack slots per the platform ABI and jumps to the pointer.

Hand-written extensions on the hot path **do not use libffi**: `system(command)` and `Config_process(self, …)` are direct C calls. You still marshal Python ↔ C with the Python C API, not libffi.

ctypes and CFFI **ABI** mode use libffi because the callee’s signature is only known from Python metadata (`argtypes`, `cdef`) at runtime. See [CFFI overview — ABI mode](https://cffi.readthedocs.io/en/stable/overview.html#simple-example-abi-level-in-line).

---

### 7.2 ctypes Mechanism

ctypes is **itself** a C extension module (`_ctypes`). Your code is Python-only.

**Full source:** [c_ext_ctypes_add](https://github.com/shan-weiqiang/python/tree/main/c_ext_ctypes_add) — [`test_ctypes_add.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_ctypes_add/test_ctypes_add.py); shared C library in [c_ext_ffi_clib](https://github.com/shan-weiqiang/python/tree/main/c_ext_ffi_clib).

Shared plain C library (`c_ext_ffi_clib/add.c`):

```c
int add(int a, int b)
{
    return a + b;
}
```

Build `libadd.so` with `make -C c_ext_ffi_clib`, then call from Python ([`CDLL`](https://docs.python.org/3/library/ctypes.html#ctypes.CDLL), [function prototypes](https://docs.python.org/3/library/ctypes.html#function-prototypes)):

```python
import ctypes
from pathlib import Path

lib = ctypes.CDLL(str(Path("c_ext_ffi_clib/libadd.so").resolve()))
lib.add.argtypes = [ctypes.c_int, ctypes.c_int]
lib.add.restype = ctypes.c_int

assert lib.add(2, 3) == 5
assert "FuncPtr" in type(lib.add).__name__
```

**Call chain:**

1. `CDLL` → `dlopen("libadd.so")`, `dlsym("add")` → raw function pointer.
2. `lib.add(2, 3)` → `_FuncPtr` callable (`ctypes.CDLL.__init__.<locals>._FuncPtr`), **not** `builtin_function_or_method` from Part II’s `PyCFunctionObject`.
3. `_ctypes` converts Python `int` → C `int`, calls through **libffi**, returns result as Python `int`.

Wrong [`argtypes`](https://docs.python.org/3/library/ctypes.html#ctypes.FunctionPrototype.__call__) / `restype` can corrupt the stack or crash — there is no compile-time check.

---

### 7.3 CFFI — ABI and API Modes

CFFI ([documentation](https://cffi.readthedocs.io/en/stable/)) offers four combinations of **ABI vs API** and **in-line vs out-of-line** ([other modes](https://cffi.readthedocs.io/en/stable/overview.html#other-cffi-modes)). The demos below use the two most common for calling an existing library.

![CFFI ABI in-line vs API out-of-line paths](/assets/images/python_c_ext_cffi_modes.png)

#### ABI mode (in-line)

Like ctypes: no C compiler step for your glue. Uses `_cffi_backend` + libffi. Mis-declared [`cdef`](https://cffi.readthedocs.io/en/stable/cdef.html) can crash ([CFFI warning](https://cffi.readthedocs.io/en/stable/overview.html#simple-example-abi-level-in-line)).

**Full source:** [c_ext_cffi_abi](https://github.com/shan-weiqiang/python/tree/main/c_ext_cffi_abi) — [`test_cffi_abi.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_cffi_abi/test_cffi_abi.py)

```python
from cffi import FFI

ffi = FFI()
ffi.cdef("int add(int a, int b);")
lib = ffi.dlopen("c_ext_ffi_clib/libadd.so")

assert lib.add(2, 3) == 5
```

`ffi.cdef` accepts C declarations (paste from a header). `ffi.dlopen` loads the `.so` at runtime — same class of dynamic call as `ctypes.CDLL`.

#### API mode (out-of-line)

CFFI generates a real C extension module ([main mode](https://cffi.readthedocs.io/en/stable/overview.html#main-mode-of-usage)): `cdef` + [`set_source`](https://cffi.readthedocs.io/en/stable/cdef.html) + compile. The compiler checks struct layouts; repeated calls are faster than ABI mode.

**Full source:** [c_ext_cffi_api](https://github.com/shan-weiqiang/python/tree/main/c_ext_cffi_api) — [`add_build.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_cffi_api/add_build.py), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_cffi_api/setup.py), [`test_cffi_api.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_cffi_api/test_cffi_api.py)

Build script (`add_build.py`):

```python
from pathlib import Path
from cffi import FFI

ffibuilder = FFI()
ffibuilder.cdef("int add(int a, int b);")

_here = Path(__file__).resolve().parent
_add_c = _here.parent / "c_ext_ffi_clib" / "add.c"

ffibuilder.set_source(
    "_add_cffi",
    '#include "add.h"',
    sources=[str(_add_c)],
    include_dirs=[str(_here)],
)
```

`setup.py` uses [`cffi_modules`](https://cffi.readthedocs.io/en/stable/overview.html) (same pattern as the CFFI distributing example):

```python
setup(
    name="add_cffi",
    cffi_modules=["add_build.py:ffibuilder"],
    setup_requires=["cffi>=1.0.0"],
)
```

Build and use:

```bash
cd c_ext_cffi_api
python3 setup.py build_ext --inplace
```

```python
from _add_cffi import lib
assert lib.add(2, 3) == 5
```

The generated `_add_cffi.abi3.so` is a **C extension** — but CFFI wrote the glue; you only supplied `cdef` and linked `add.c`.

---

### 7.4 ctypes vs CFFI vs Hand-Written Extension vs pybind11

![Four approaches: ctypes, CFFI, hand-written C extension, pybind11](/assets/images/python_c_ext_three_approaches.png)

| | ctypes | CFFI ABI | CFFI API | Hand-written (Part I) | pybind11 (Part VII) |
|---|---|---|---|---|---|
| **pip / stdlib** | stdlib | needs `cffi` | needs `cffi` + build | `setup.py` + compiler | `setup.py`/CMake + pybind11 |
| **You write** | Python + `argtypes` | Python + `cdef` | `cdef` + build script | C + Python C API | C++ binding code |
| **Glue module** | `_ctypes` + libffi | `_cffi_backend` + libffi | generated `.so` | your `mymodule.so` | your `mymodule.so` |
| **Callable type** | `_FuncPtr` | via backend | `lib.add` in generated module | `builtin_function_or_method` | `builtin_function_or_method` |
| **Type safety** | runtime only | runtime only (ABI) | compile-time (API) | C compiler | C++ compiler + templates |
| **Custom `PyTypeObject`** | poor fit | poor fit | limited | full (`Config`, §2.2) | full (generated) |
| **Target library** | any `.so` | any `.so` | link sources / libs | whatever you link or embed | C++ compiled into extension |

**Execution contrast (Part II):** `config.process()` on [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) yields `PyCFunctionObject` → direct `Config_process` in C. `lib.add(2, 3)` via ctypes goes through `_FuncPtr` → `_ctypes` → libffi → `add` in `libadd.so` — no `PyMethodDef` on your side, no `Config` type.

---

### 7.5 When to Use Which

- **ctypes** — stdlib, quick `dlopen`, simple C signatures; good when you cannot add dependencies. See [ctypes](https://docs.python.org/3/library/ctypes.html).
- **CFFI ABI** — nicer `cdef`, [`ffi.new`](https://cffi.readthedocs.io/en/stable/overview.html#struct-array-example-minimal-in-line), buffers; same runtime model as ctypes. See [CFFI overview](https://cffi.readthedocs.io/en/stable/overview.html).
- **CFFI API** — repeated calls, structs, compile-time layout checks; still less boilerplate than hand-written extensions for flat C APIs.
- **Hand-written C extension** — custom Python types, capsules, tight error handling, maximum control (Parts I–II).
- **pybind11** — same integration as a hand-written extension, but binding code in C++ with generated `PyTypeObject` and casters; see [Part VII](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html).

The [ctypes introduction](https://docs.python.org/3/library/ctypes.html) states the C extension interface is specific to CPython; ctypes and CFFI are often **more portable across Python implementations** for *calling C functions* because your integration code stays in Python (plus CFFI’s generated shim in API mode). They do not replace C extensions when the product **is** a Python module with classes and methods designed in C.

For **ctypes struct mirroring, keepalive, and handles vs user API** (fd, capsule, internal `Structure` — not the public wrapper classes) beyond §7.2’s scalar `add()` — see [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html). For a **C++ handle pool** with integer handles, `TypeId` dispatch, and complex-type return patterns through ctypes — see [Part V — ctypes Handle Pool Design Pattern](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html).

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html)
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html)
- [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html)
- [Part V — ctypes Handle Pool Design Pattern](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html)
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html)
- [ctypes — Python 3 documentation](https://docs.python.org/3/library/ctypes.html)
- [CFFI documentation](https://cffi.readthedocs.io/en/stable/) — [overview](https://cffi.readthedocs.io/en/stable/overview.html), [ABI example](https://cffi.readthedocs.io/en/stable/overview.html#simple-example-abi-level-in-line), [API / main mode](https://cffi.readthedocs.io/en/stable/overview.html#main-mode-of-usage), [cdef](https://cffi.readthedocs.io/en/stable/cdef.html)
- [Extending Python with C or C++](https://docs.python.org/3/extending/extending.html) — when you still need a hand-written extension
