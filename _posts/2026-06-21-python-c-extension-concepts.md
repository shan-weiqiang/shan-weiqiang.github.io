---
layout: post
title:  "Python/C VIII — Extensions vs Bindings"
date:   2026-06-21 10:17:40 +0800
tags: [python]
---

* toc
{:toc}

This article is Part VIII of the Python C extension series — a **conceptual capstone**. It does not introduce new APIs or demos. It clarifies vocabulary and architecture assumed (and sometimes mixed) across the earlier parts:

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) — hand-written C API, `PyTypeObject`
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) — bytecode vs C dispatch
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) — runtime FFI via `_ctypes`
- [Part IV — Complex ctypes Structs](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) — struct mirroring, user API
- [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) — C++ behind C ABI + handles
- [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) — production hybrid stack
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) — compile-time C++ extension authoring
- [Part IX — Inheritance Handle Pool](https://shan-weiqiang.github.io/2026/07/11/python-c-ctypes-handle-pool-inheritance.html) — C++ inheritance behind handle pool

**Two ideas this part separates:**

1. **Extension module** — a compiled `.so` Python imports; speaks the C API; sits on **Layer 2** below. Includes **your** modules (C API, pybind11) **and** ready-made ones (`_ctypes`, `_cffi_backend`).
2. **Binding** — a **process on Layer 1 (pure Python)**: call existing C/C++ through an extension on Layer 2, usually with Python glue and wrapper classes. Your target `libfoo.so` does not need `Python.h`.

Both paths ultimately rest on the **Python C API** (`PyObject`, `PyTypeObject`, refcounts) inside Layer 2 extensions, and **bidirectional marshalling** between Python values and C/C++ data.

### Where to read next

| Concept | Part | Demo (if any) |
|---|---|---|
| Hand-written extension module | I §1–§2 | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) |
| `PyCFunctionObject` dispatch | II §5–§6 | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) |
| Scalar ctypes / libffi | III §7.2 | [c_ext_ctypes_add](https://github.com/shan-weiqiang/python/tree/main/c_ext_ctypes_add) |
| Struct mirroring + user API | IV §8 | [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) |
| C++ handle pool | V §9 | [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding) |
| Hybrid binding system | VI §10 | [ros2_binding_demo](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) |
| pybind11 extension authoring | VII §11 | [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) |
| C++ inheritance handle pool | IX §13 | [c_ext_handle_inheritance](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance) |

---

## Section 12: Extensions vs Bindings — Conceptual Map

### 12.0 The Three-Layer Stack

Read the series **top to bottom**. Bindings are **not** parallel to extensions — they **live above** the extension layer and **use** it.

![Three layers: pure Python, then all C extension modules on one tier, then C or C++](/assets/images/python_c_ext_stack_layers.png)

| Layer | What lives here | Examples in this series |
|---|---|---|
| **Layer 1 — Pure Python** | Application code; **binding glue** (Python wrappers, `argtypes`, `_fields_`, keepalive) | Part IV `bindings.py`, `InputRecordPy`; Part V `HandleResource`; scalar `CDLL` setup (Part III) |
| **Layer 2 — C extension modules** | **All** importable `.so` that speak the C API — same tier | **User-built:** Part I `mymodule.so`, Part VII pybind11 `mymodule.so`. **Ready-made:** stdlib `_ctypes`, pip `_cffi_backend`. **Generated:** CFFI API shim (Part III) |
| **Layer 3 — C / C++** | Native implementation | Code **inside** your extension (Parts I, VII); **existing** `libfoo.so` with no `Python.h` (Parts III–V) |

**Critical clarification:** `_ctypes` and `_cffi_backend` **are** C extension modules — the same *kind* of artifact as `mymodule.cpython.so` built with the C API or pybind11. CPython ships `_ctypes`; you install `_cffi_backend`. You do not author them; you **import** them. pybind11 and the raw C API are **tools to author** Layer 2 modules; ctypes/CFFI are **pre-built** Layer 2 modules you reuse.

**Binding** = Layer 1 Python code that calls Layer 2 (`_ctypes`) to reach Layer 3 (`libfoo.so`). **Extension authoring** = building a Layer 2 module whose Layer 3 implementation is compiled **into** the same `.so`, then using it directly from Layer 1 (`import mymodule` — no binding glue required).

---

### 12.1 Two Different Goals

The series covers two **different goals** that are easy to conflate because both connect Python to native code:

| | **Extension authoring** | **Binding** |
|---|---|---|
| **Goal** | Implement a normal Python module in C/C++ | Use an existing C/C++ library from Python |
| **Where your work lives** | **Layer 2** — you build `mymodule.cpython.so` | **Layer 1** — Python glue; **Layer 3** — plain `libfoo.so` |
| **Layer 2 module used** | **your** extension (C API or pybind11) | **ready-made** `_ctypes` / `_cffi_backend` (or CFFI-generated shim) |
| **Typical Layer 1 usage** | `import mymodule` — direct, no wrapper | `from my_pkg import Foo` — Python wrapper over glue |
| **Integrator needs python-dev?** | **yes** — to compile your extension | **no** for ctypes user (only target `.so`; `_ctypes` already installed) |
| **Python wrapper on Layer 1?** | usually **no** | often **yes** — mirrors, handles, keepalive |
| **Layer 3 includes `Python.h`?** | **yes** (inside your extension) | **no** (plain library) |

![Extension authoring vs binding: both use Layer 2 extensions; binding adds Layer 1 glue](/assets/images/python_c_ext_extension_vs_binding_layers.png)

**Extension authoring:** you produce a **Layer 2** module. Layer 1 does `import mymodule` and calls native API directly — Parts I and VII. Part II explains dispatch into such modules.

**Binding:** you write **Layer 1** glue that imports a **Layer 2** extension someone else already built (`_ctypes`, not a module you authored for your library). That extension reaches **Layer 3** `libfoo.so`. Parts III–V are binding patterns. Your `libstruct_demo.so` is **not** a Python extension; `_ctypes` **is**.

#### Overloaded word: "binding"

Terminology in the wild is messy:

- **pybind11** documentation says "create Python **bindings**" — but the **artifact** is still an **extension module** you compile (Part VII).
- **Part I §2** sometimes says "binding" when exposing a C struct via `PyTypeObject` — that is **extension authoring**, not the binding pattern above.
- **Part VI** title uses "Message Bindings" for a **whole stack** (Python classes + several `.so` files + capsules).

Part VIII uses **binding** for the **Layer 1 process** of integrating existing Layer 3 libraries via a Layer 2 extension. **Extension module** names the **Layer 2 artifact** — whether you built it (C API, pybind11) or Python ships it (`_ctypes`).

---

### 12.2 The Python C API as the Shared Floor

Whatever path you choose, something must speak **`PyObject*`** — allocate Python objects, parse arguments, return values, manage refcounts. That is the **[Python C API](https://docs.python.org/3/c-api/index.html)**.

> To connect Python and C/C++ at all, a **Layer 2 extension module** must speak `PyObject*` — allocate Python objects, parse arguments, return values, manage refcounts. That is the **[Python C API](https://docs.python.org/3/c-api/index.html)** inside `_ctypes`, `_cffi_backend`, `mymodule.so`, and every other `.so` Python imports as a module.
>
> **Extension authoring** (Parts I, VII): you write the Layer 2 module; it marshals directly (C API) or via pybind11-generated wrappers. **Binding** (Parts III–V): your code stays on Layer 1; marshalling happens **inside** the ready-made Layer 2 module (`_ctypes` + libffi) on your behalf.

At the C level, the recurring work is **bidirectional marshalling** — always inside Layer 2, regardless of who built that module:

| Direction | Your extension (Layer 2, Parts I, VII) | Ready-made extension (Layer 2, Parts III–V) |
|---|---|---|
| **Python → C/C++** | `PyArg_ParseTuple`; pybind11 casters | `_ctypes` reads `argtypes` / `_fields_`; libffi packs |
| **C/C++ → Python** | `PyLong_FromLong`; `py::cast` | `_ctypes` builds `Structure` / return values from `restype` |

The diagram below is a **layered stack** (top → bottom): Layer 1 Python values; Layer 2 extension modules where marshalling logic runs; **Python C API as the bottom floor** inside those modules; C/C++ native data below the marshalling boundary.

![Layered marshalling stack: Pure Python, extension modules, Python C API floor, then C/C++ data](/assets/images/python_c_ext_marshalling_core.png)

**PyTypeObject** (Part I) is part of the same floor: when an extension exposes a class, it registers a type object so Python's attribute protocol, `isinstance`, and `tp_call` machinery apply. pybind11 generates that registration for you (Part VII). ctypes struct mirroring (Part IV) **does not** create a `PyTypeObject` for your C struct — it lays out bytes in a `Structure` buffer and passes pointers through `_ctypes`.

---

### 12.3 Extension Modules — Layer 2 (Parts I, II, VII)

Everything on **Layer 2** is a C extension module: `PyInit_*`, links `libpython`, speaks the C API internally.

**User-built** (you compile):

- Part I — hand-written `PyModuleDef`, `PyTypeObject`
- Part VII — pybind11 `PYBIND11_MODULE` → same runtime objects, less boilerplate

**Ready-made** (already compiled, you import):

- **`_ctypes`** — stdlib; Part III §7
- **`_cffi_backend`** — pip package; Part III §7

After `import mymodule` (your extension) or `import _ctypes` (stdlib), Layer 1 calls into Layer 2. For **extension authoring**, the product **is** that import:

```python
import mymodule
config = mymodule.Config(timeout=30, url="http://example.com", ssl=True)
config.process()
```

Parts I ([`c_ext_config_basic`](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic)) and VII ([`c_ext_pybind11_config`](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config)) expose the **same** Layer 1 API; one hand-writes `ConfigType`, the other uses `py::class_<Config>`. Both produce **your** Layer 2 `mymodule.cpython.so`.

**Execution (Part II):** `config.process()` → **`PyCFunctionObject`** in your Layer 2 module → direct native call. No libffi on the hot path.

---

### 12.4 Binding — Layer 1 Glue Using Layer 2 Extensions (Parts III–V)

A **binding** is **not** a Layer 2 artifact. It is **Layer 1 Python** (plus your plain Layer 3 library) that **uses** a ready-made Layer 2 extension:

1. **Layer 3:** existing native code (`libadd.so`, `libstruct_demo.so`, C++ behind `extern "C"` bridge) — **no** `Python.h`.
2. **Layer 2:** import **`_ctypes`** or **`_cffi_backend`** — pre-built extension modules, same tier as `mymodule.so` but authored by CPython / cffi maintainers.
3. **Layer 1:** your Python glue — `CDLL`, `argtypes`/`restype`, `ctypes.Structure` `_fields_`, keepalive, wrapper classes.

Part IV's [`bindings.py`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/bindings.py) is Layer 1: it imports `_ctypes` (Layer 2), loads `libstruct_demo.so` (Layer 3), defines `Structure` subclasses, exposes `transform()` and **`InputRecordPy`**. Part V adds C++ **`HandlePool`** on Layer 3 with a C ABI shim — still Layer 1 ctypes glue calling `_ctypes`.

**You do not emit `PyInit_*` for your library** when binding via ctypes. You also **do not** skip the extension layer — `_ctypes` **is** the extension; binding lives **above** it.

**The integrator does not compile Layer 2** for ctypes (CPython already did). You **do** need to build Layer 3 if you maintain `libfoo.so`.

---

### 12.5 Hybrid Cases — When Binding Still Ships Extensions

Real stacks blur the clean split. Treat these as **labeled positions** on the same diagram, not counterexamples:

| Case | Layer 2 artifact | Layer 1 / 3 role | Part |
|---|---|---|---|
| **CFFI API mode** | generated `_add_cffi.cpython.so` (you build Layer 2 shim) | Layer 1 `cdef` + import generated module | III |
| **pybind11** | `mymodule.cpython.so` (extension authoring, not binding) | Layer 1: direct `import` | VII |
| **ROS 2 / rosidl** | multiple Layer 2 `.so` + `_rclpy_pybind11` | Layer 1 Python classes + binding stack | VI |
| **Part I `PyCapsule`** | your Layer 2 extension | exposes binding-style opaque handle API | I §2.1 |

Hybrids show **which Layer 2 modules** a production stack composes — not a fourth layer. CFFI API mode blurs lines because **you** generate a Layer 2 shim, closer to extension authoring than pure ctypes (where Layer 2 is always `_ctypes`).

---

### 12.6 Python Wrapper Code — Who Needs It?

| Pattern | Python wrapper? | Example |
|---|---|---|
| Extension `Config` | **no** | `import mymodule; mymodule.Config(...)` — Parts I, VII |
| Scalar ctypes | **minimal** | `CDLL("libadd.so"); lib.add(2, 3)` — Part III |
| ctypes complex struct | **yes** (recommended) | `InputRecordPy`, `transform()` — Part IV §8.9 |
| Handle pool | **yes** | `Config`, `Counter`, `*Resource` — Part V |
| ROS 2 messages | **yes** | generated `_demo_status.py` + user nodes — Part VI |

**Why bindings tend to need wrappers:**

- **Layout fidelity** — `_fields_` and keepalive are easy to get wrong; a user API hides them (Part IV).
- **Lifetime** — pointers into C heap or pool objects need explicit `close()` / context managers (Part IV §8.8, Part V).
- **Handle indirection** — Python must not hold raw C++ addresses across ctypes (Part V).
- **Ergonomic API** — application code should not assemble FFI details on every call.

Extensions push marshalling **into Layer 2** (your `.so`), so Layer 1 imports the module directly. Bindings keep orchestration on **Layer 1** and delegate marshalling to a **ready-made Layer 2** extension (`_ctypes`).

---

### 12.7 Decision Guide and Series Map

**Which goal do you have?**

1. **Implement a module API in C/C++** → extension authoring (Part I or VII).
2. **Call an existing `.so` from Python with stdlib-only glue** → binding via ctypes (Parts III–V).
3. **Production stack with codegen and multiple `.so` layers** → study hybrids (Part VI; CFFI API in Part III).

| Part | Primary role | Layer 2 module | Layer 1 wrapper typical? |
|---|---|---|---|
| **I** | Extension authoring | **your** `mymodule.so` | no |
| **II** | Execution model for Layer 2 | — | — |
| **III** | Binding (+ CFFI hybrid) | `_ctypes` / `_cffi_backend` / generated shim | minimal to moderate |
| **IV** | Binding | `_ctypes` | yes (user API) |
| **V** | Binding | `_ctypes` + Layer 3 C ABI shim | yes |
| **VI** | Hybrid binding system | multiple Layer 2 `.so` | yes |
| **VII** | Extension authoring | **your** `mymodule.so` via pybind11 | no |

**Compile-time vs runtime (Part VII §11.9):** orthogonal to the layer model. pybind11 resolves signatures when **you compile** your Layer 2 module; ctypes binding resolves them when **`_ctypes` calls libffi** at runtime. Both are Layer 2 extensions; the difference is **who builds Layer 2** and **when** layout/signature metadata is fixed.

---

### 12.8 Terminology Cheat Sheet

Use these terms consistently when reading or writing about native integration:

- **Extension module (Layer 2)** — any importable `.so` with `PyInit_*` that speaks the C API: **your** module (C API, pybind11) **or** ready-made `_ctypes`, `_cffi_backend`.
- **Extension authoring** — you build a Layer 2 module; Layer 1 uses `import mymodule` directly.
- **Binding** — Layer 1 process: Python glue + wrapper classes that call a Layer 2 extension to reach Layer 3 `libfoo.so`.
- **Ready-made extension** — Layer 2 module you import but did not author (`_ctypes`, `_cffi_backend`); same tier as user-built modules.
- **Python glue / mirror / user API** — Layer 1 binding code (`bindings.py`, `InputRecordPy`, `HandleResource`).
- **Marshalling** — `PyObject` ↔ C/C++ conversion; always happens **inside** Layer 2.
- **Target library (Layer 3)** — plain `libfoo.so` (binding) vs implementation compiled into your extension (extension authoring).

---

### 12.9 Binding Rests on C Extensions — Forms Differ in How Much Sits Above

Sections 12.0–12.8 separate **extension module** (Layer 2 artifact) from **binding** (Layer 1 process). That split is useful for navigation. One invariant cuts across both labels:

> **Every binding path reaches native code through a C extension module.** Binding is not an alternative to extensions — it is **extension plus additional code**, in one of several forms.

A C extension module is the **mandatory floor**: something with `PyInit_*` that speaks `PyObject*` and performs marshalling (§12.2). **Binding glue is mandatory too**, but it is **compiled native code** inside an extension — hand-written C API, pybind11 C++, libffi logic in **`_ctypes`**, or the backend in **`_cffi_backend`**.

User-facing **`CDLL`**, **`argtypes`**, **`Structure`**, and CFFI **`cdef`** belong in the **application layer**: ordinary Python code the user writes. They are not glue — they declare layouts and signatures **to** an extension whose glue is already compiled. When ctypes must reach **C++**, an **`extern "C"` bridge** (`bridge.cpp`, no `Python.h`) exposes stable C symbols in the native library (Part V).

What varies is whether the application adds an optional **mirror** row (`Node`, `HandleResource`, …) and whether native glue is authored by you (pybind11 / hand C) or shipped inside **`_ctypes`** / **`_cffi_backend`**.

The diagram below is a **layered stack** read top to bottom. **Application** includes direct imports, ctypes/CFFI calls in user scripts, and high-level clients like **rclpy**. Only the **mirror** row may be skipped. **Compiled glue** and the **C extension floor** are always present — for ctypes/CFFI, glue is **inside** `_ctypes` / `_cffi_backend`, not in user Python.

![Binding stack: application includes user ctypes/CFFI; compiled glue in extension floor; optional mirror](/assets/images/python_c_ext_binding_on_extension.png)

**How to read it:**

1. **Application** — all user Python: `import mymodule`; **`CDLL` / `argtypes` / `Structure`** (when you call ctypes directly in your script); **`cdef` / dlopen**; `from pkg import Foo`; `rclpy.spin`. None of this is binding glue — it calls into extensions that already contain glue.
2. **Python mirror / user API** — optional wrappers for ergonomics and lifetime. **rclpy** puts `Node`, `Publisher`, `Executor` here; Part IV/V put `InputRecordPy`, `HandleResource` here. On the **`from pkg import Foo`** path, the user script stops here — **`CDLL` / `argtypes` / `Structure` live inside the package**, not in the user's file. Bare ctypes scripts skip this row and use the middle application node instead.
3. **Binding glue** — **mandatory compiled code**, visible as its own row only when **you** author it (hand C API, pybind11 C++ → your `.so`). For ctypes/CFFI, marshalling logic is **folded into** `_ctypes` / `_cffi_backend` on the next row — both **link against `libffi.so`** at runtime to pack arguments and invoke foreign functions.
4. **C extension modules** — mandatory runtime floor.
5. **`libffi.so`** — shared native dependency of **`_ctypes`** and **`_cffi_backend`** (Part III §7.2). Not a Python layer; the compiled FFI engine both extensions use to call `libfoo.so`.
6. **Native C / C++ — target libraries** — plain C `libfoo.so`; **`extern "C"` bridge** wrapping C++ (Part V); or **rcl** / **rmw**.

#### The `from pkg import Foo` path — wrapper hides ctypes from the user

The diagram edge **`from pkg import Foo` → wrapper → `_ctypes`** means: your **application script** imports a friendly name; the **package** owns the ctypes setup and calls `_ctypes` on your behalf.

**What the user writes** (application — no `CDLL`, no `_fields_`):

```python
from mypkg import InputRecordPy, transform

with transform(InputRecordPy("sensor-A", version=2, origin=(10, 20)), scale=1.5,
               min_weight=20, top_n=2) as out:
    print(out.title)
```

**What the package contains** (mirror / wrapper — ctypes lives here, not in user code):

```python
# mypkg/bindings.py
import ctypes

_lib = ctypes.CDLL("libstruct_demo.so")
_lib.transform_record.argtypes = [ctypes.POINTER(InputRecord), ...]
_lib.transform_record.restype = OutputRecord

class InputRecordPy:
    """User-facing mirror — hides Structure layout and keepalive."""
    def to_ctypes(self):
        ...  # build InputRecord, return (struct, keepalive_list)

def transform(record: InputRecordPy, scale, min_weight, top_n):
    c_input, keepalive = record.to_ctypes()
    c_output = _lib.transform_record(ctypes.byref(c_input), ...)  # → _ctypes → libfoo.so
    return OutputRecordPy.from_ctypes(c_output)
```

Read the call chain:

```text
user script          wrapper (mypkg)              extension        libffi           target
───────────          ───────────────              ─────────        ──────           ──────
transform(...)  →    _lib.transform_record(...)  →  _ctypes     →  libffi.so  →  libstruct_demo.so
                     CDLL · argtypes · Structure
```

Both **`_ctypes`** and **`_cffi_backend`** load **`libffi.so`** to perform the actual foreign-function call; your **`argtypes`** / **`cdef`** only tell them what to pack.

The user's file is the top row only. **`InputRecordPy`** and **`transform`** are the mirror. **`CDLL` / `argtypes` / `Structure`** sit in `bindings.py` — still Python application code, but **authored by the library maintainer**, not repeated in every user script. That is why the diagram shows two application entry points: **`CDLL · argtypes`** when you ctypes directly, and **`from pkg import Foo`** when a package wraps the same machinery for you.

**Synthesis:** **Application** = user Python (including ctypes/CFFI declarations). **Glue** = compiled marshalling (in your extension or in `_ctypes` / `_cffi_backend`). Do not place `argtypes` in the glue layer — user code sets them; **`_ctypes`** executes them.

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html)
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html)
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html)
- [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html)
- [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html)
- [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html)
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html)
- [Part IX — Inheritance Handle Pool](https://shan-weiqiang.github.io/2026/07/11/python-c-ctypes-handle-pool-inheritance.html)
- [Extending Python with C or C++](https://docs.python.org/3/extending/extending.html)
- [Python/C API Reference](https://docs.python.org/3/c-api/index.html)
- [ctypes — Python 3 documentation](https://docs.python.org/3/library/ctypes.html)
