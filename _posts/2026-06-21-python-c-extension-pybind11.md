---
layout: post
title:  "Python/C VII — pybind11"
date:   2026-06-21 09:00:00 +0800
tags: [python]
---

* toc
{:toc}

This article is Part VII of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) covers hand-written extension functions and `PyTypeObject` binding. [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) covers bytecode, `tp_call`, and C method dispatch. [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) covers runtime FFI through `_ctypes` and libffi. [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) covers struct mirroring and keepalive. [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) covers C++ behind a C ABI and integer handles. [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) applies capsule bindings at production scale; it already mentions `_rclpy_pybind11` as a real pybind11 module. [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html) is the conceptual capstone for the series.

Part VII covers **pybind11**: how it works internally, how binding code accepts and returns Python objects at the C++ level, how it compares to hand-written C API code (Part I), and how it differs from **ctypes** on the compile-time vs runtime axis.

Runnable demo: [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) in the [python](https://github.com/shan-weiqiang/python) repository — a pybind11 reimplementation of Part I's [`c_ext_config_basic`](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) `Config` type, plus `inspect(py::object)` and `summarize()` returning a Python `dict`.

```bash
pip install pybind11
cd c_ext_pybind11_config
python3 setup.py build_ext --inplace
python3 test_pybind11_config.py
```

| Section | Demo folder |
|---|---|
| §11.2–11.7 | [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) — [`config.hpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_pybind11_config/config.hpp), [`bindings.cpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_pybind11_config/bindings.cpp), [`test_pybind11_config.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_pybind11_config/test_pybind11_config.py) |
| §11.7 contrast (hand-written) | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) (Part I §2.2.2) |
| §11.9 contrast (ctypes) | [c_ext_ctypes_add](https://github.com/shan-weiqiang/python/tree/main/c_ext_ctypes_add) (Part III §7.2) |
| §11.9 contrast (ctypes struct) | [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) (Part IV) |
| §11.1 forward link | [ros2_binding_demo](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) — `_rclpy_pybind11` (Part VI) |

---

## Section 11: pybind11 — Compile-Time C++ Bindings

### 11.1 Position in the Series

The series so far covers two opposite poles:

- **Part I (hand-written C API):** full Python integration — real `PyTypeObject`, attributes, `isinstance`, exceptions — but ~100 lines of boilerplate per simple type.
- **Parts III–V (ctypes):** stdlib Python glue, no per-library `PyInit_*`, but runtime libffi dispatch, manual struct layout mirroring, and awkward C++ (Part V's handle pool exists precisely because ctypes cannot speak C++ classes natively).

**pybind11** sits between them on the *integration* axis and beside Part I on the *mechanism* axis:

| Axis | ctypes (Parts III–V) | pybind11 (Part VII) | Hand-written C API (Part I) |
|---|---|---|---|
| **When binding is resolved** | runtime (libffi + Python metadata) | compile time (C++ templates) | compile time (your C code) |
| **User binding code language** | Python | C++ | C |
| **Bridge you import** | pre-built `_ctypes` (stdlib) | **your** `mymodule.cpython-….so` | **your** `mymodule.cpython-….so` |
| **`PyTypeObject` / attributes** | poor fit | full (generated) | full (hand-written) |

Part VI showed `_rclpy_pybind11.cpython-312-aarch64-linux-gnu.so` — production proof that pybind11 modules are first-class C extensions with SOABI-tagged filenames, same as Part I's hand-written modules.

---

### 11.2 What pybind11 Is (and Is Not)

[pybind11](https://github.com/pybind/pybind11) is a **header-only C++11 library**. You `#include <pybind11/pybind11.h>`, write binding code in C++, and compile it into a shared library that Python imports. There is:

- **No** separate pybind11 runtime `.so` to link against (only `libpython`).
- **No** code generator step (contrast CFFI API mode in Part III, which emits C and compiles it).
- **No** pure-Python binding path (contrast ctypes, where user code stays in Python and calls the ready-made `_ctypes` extension).

Minimal binding for the demo `Config` type:

```cpp
#include <pybind11/pybind11.h>
namespace py = pybind11;

PYBIND11_MODULE(mymodule, m) {
    py::class_<Config>(m, "Config")
        .def(py::init<int, const std::string&, bool>(),
             py::arg("timeout") = 0, py::arg("url") = "", py::arg("ssl") = false)
        .def_readwrite("timeout", &Config::timeout)
        .def_property("server_url",
            [](const Config &c) { return c.server_url; },
            [](Config &c, const std::string &v) { c.server_url = v; })
        .def_readwrite("enable_ssl", &Config::enable_ssl)
        .def("process", &Config::process);
}
```

Python usage matches Part I exactly:

```python
import mymodule

config = mymodule.Config(timeout=30, url="http://server.com", ssl=True)
config.timeout = 60
assert config.process() == 120
assert isinstance(config, mymodule.Config)
```

---

### 11.3 Internal Architecture — Compile Time, Import Time, Call Time

pybind11 is not a parallel object model. It **generates** the same CPython machinery Part I builds by hand — `PyInit_*`, `PyTypeObject`, method wrappers, argument parsing — using C++ templates at compile time and registration calls at import time.

![pybind11 internal flow from PYBIND11_MODULE through make_new_python_type to C++ call](/assets/images/python_c_ext_pybind11_internals.png)

#### Compile time

When you write `m.def("add", &add)` or `py::class_<Config>(...)`, the compiler instantiates template code in pybind11 headers (`cpp_function`, `class_`, **type casters**). Each C++ signature yields concrete wrappers that know how to:

- parse `PyObject*` arguments into C++ types;
- call your function or method;
- convert the return value back to `PyObject*`.

Function signatures for `help()` are precomputed with `constexpr` where possible — one reason pybind11 binaries are smaller than Boost.Python's.

#### Import time

`PYBIND11_MODULE(mymodule, m)` expands to a standard **`PyInit_mymodule`** entry point (Python 3). When Python runs `import mymodule`:

1. `PyInit_mymodule` runs.
2. `py::class_<Config>` calls **`make_new_python_type`** (in `pybind11/detail/class.h`): allocates a `PyHeapTypeObject`, sets `tp_name`, `tp_base` → internal `pybind11_object`, `tp_basicsize = sizeof(instance)`, calls **`PyType_Ready`**, registers the type on the module with `setattr`.
3. `m.def(...)` registers free functions as descriptors on the module dict.

This is the same registration sequence as Part I's `PyType_Ready(&ConfigType)` + `PyModule_AddObject(m, "Config", ...)`, but generated from declarative C++.

#### Call time

When Python calls `config.process()`:

1. Attribute lookup finds a bound method descriptor (pybind11's `cpp_function` wrapper).
2. The wrapper extracts the C++ `Config` from the pybind11 **`instance`** layout inside the Python object.
3. It calls `Config::process()` directly — **no libffi** (contrast Part III's ctypes path in [`python_c_ext_ctypes_call_flow.png`](/assets/images/python_c_ext_ctypes_call_flow.png)).

![pybind11 call flow: import mymodule then direct C++ call, no libffi](/assets/images/python_c_ext_pybind11_call_flow.png)

| Layer | pybind11 | Raw C API (Part I) |
|---|---|---|
| Module entry | `PYBIND11_MODULE` → `PyInit_*` | `PyModuleDef`, `PyModule_Create` |
| Free functions | `m.def` → `cpp_function` | `PyMethodDef`, `PyArg_ParseTuple` |
| Classes | `py::class_<T>` → `make_new_python_type` | static `PyTypeObject`, `PyType_Ready` |
| Instances | `instance` struct: C++ object + holder in `tp_basicsize` buffer | custom `ConfigObject` with `PyObject_HEAD` |
| Base infrastructure | internal `pybind11_object` supplies `tp_new`, `tp_dealloc` | you write `Config_new`, `Config_dealloc` |
| Methods / properties | descriptors on type `__dict__` | `tp_methods`, `tp_getset` |

The runtime picture is the same as Part I's [`python_c_ext_object_type_pairing.png`](/assets/images/python_c_ext_object_type_pairing.png): `mymodule.Config` is a real `PyTypeObject`; each instance has `ob_type` pointing at it; `isinstance(config, mymodule.Config)` works through the normal CPython type machinery.

---

### 11.4 `py::class_` and `PyTypeObject` Generation

Part I §2.2.2 defines `ConfigObject` and a static `ConfigType` with explicit slots:

```c
typedef struct {
    PyObject_HEAD
    int timeout;
    PyObject *server_url;
    bool enable_ssl;
} ConfigObject;

static PyTypeObject ConfigType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mymodule.Config",
    .tp_basicsize = sizeof(ConfigObject),
    .tp_new = Config_new,
    .tp_init = (initproc)Config_init,
    .tp_dealloc = (destructor)Config_dealloc,
    .tp_getset = Config_getsetters,
    .tp_methods = Config_methods,
};
```

pybind11's equivalent in [`bindings.cpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_pybind11_config/bindings.cpp) is ~15 lines of `py::class_<Config>` (see §11.2). Under the hood, `make_new_python_type`:

1. Allocates a **`PyHeapTypeObject`**.
2. Sets `type->tp_name` to the fully qualified name (e.g. `mymodule.Config`).
3. Sets `type->tp_base` to **`pybind11_object`** — an internal base type that already implements generic `tp_new` (`pybind11_object_new` → `tp_alloc` + allocate holder layout) and `tp_dealloc`.
4. Sets `type->tp_basicsize = sizeof(instance)` where `instance` is pybind11's internal struct wrapping the C++ object.
5. Calls **`PyType_Ready(type)`** and **`setattr(module, "Config", type)`**.

**Two-phase construction** (same model as Part II §5 for any Python class):

| Phase | Slot / method | pybind11 | Part I |
|---|---|---|---|
| Allocate shell | `tp_new` | `pybind11_object_new` | `Config_new` |
| Construct payload | `tp_init` / `__init__` | `py::init<...>` wrapper | `Config_init` |

`py::init<int, const std::string&, bool>()` registers an `__init__` that placement-new's a C++ `Config` into the instance holder. Omitting `py::init` leaves the default `pybind11_object_init`, which raises `TypeError: No constructor defined!`.

---

### 11.5 Type Casters — Crossing the Boundary

pybind11 moves data across the Python/C++ boundary through **type casters** — template specializations selected at **compile time** from C++ type information.

Three interaction modes (see [cast overview](https://pybind11.readthedocs.io/en/latest/advanced/cast/overview.html)):

| Mode | C++ side | Python side | What happens |
|---|---|---|---|
| **Wrapper over C++** | Native `Config` | Python proxy | Zero-copy: Python holds a shell around the real C++ instance (`py::class_`) |
| **Wrapper over Python** | `py::dict`, `py::list` | Native object | Python object referenced, not copied |
| **Conversion** | `std::vector<int>` | `list` | Data copied both ways |

Contrast Part IV's ctypes struct mirroring: ctypes requires you to describe C layout with `_fields_` and manually match `sizeof`/`offsetof`. pybind11 never exposes C++ memory layout to Python — integration is through generated wrappers and casters, not byte-level struct equivalence.

Built-in casters cover scalars, strings, STL containers (`#include <pybind11/stl.h>`), chrono, Eigen, NumPy, and more. Custom types use `py::class_` or a custom type caster specialization.

---

### 11.6 Accepting and Returning Python Objects in User Code

Binding code is C++, but you often need to accept arbitrary Python values, return Python collections, or call back into Python. pybind11 wraps `PyObject*` in RAII types.

**Full source:** [`bindings.cpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_pybind11_config/bindings.cpp) — `inspect()` and `summarize()`.

#### Accept: `py::object` and typed wrappers

```cpp
void inspect(py::object obj) {
    if (obj.is_none())
        return;

    if (py::isinstance<py::dict>(obj)) {
        for (auto item : obj.cast<py::dict>())
            /* ... */;
    } else if (py::isinstance<Config>(obj)) {
        const Config &cfg = obj.cast<const Config &>();
        /* ... */
    }
}
```

Export:

```cpp
m.def("inspect", &inspect, py::arg("obj"));
```

```python
mymodule.inspect({"a": 1})
mymodule.inspect(config)
mymodule.inspect(None)
```

| Parameter type | Accepts from Python | Notes |
|---|---|---|
| `py::object` | anything | inspect with `py::isinstance`, `cast` |
| `const py::dict&` | dict only | implicit check; `TypeError` if wrong |
| `Config&` / `const Config&` | bound `Config` instance | unwraps C++ object from pybind11 shell |
| `py::args`, `const py::kwargs&` | `*args`, `**kwargs` | `kwargs` must be last parameter |

Use **`py::handle`** for borrowed short-lived references (no refcount increment); **`py::object`** for stored/returned values (RAII, increments refcount). Wrong `cast<T>()` throws **`py::cast_error`**.

#### Return: Python objects from C++

```cpp
py::dict summarize(const Config &cfg) {
    py::dict out;
    out["timeout"] = cfg.timeout;
    out["server_url"] = cfg.server_url;
    out["enable_ssl"] = cfg.enable_ssl;
    out["process_result"] = cfg.process();
    return out;   // refcount managed; Python receives a new dict
}
```

Any `py::object` subclass (`py::dict`, `py::list`, `py::str`, …) converts to a return value. For bound C++ types, returning `Config` by value creates or reuses a Python wrapper.

#### Call Python from C++

```cpp
py::module_ math = py::module_::import("math");
py::object result = math.attr("sqrt")(py::float_(42));
double x = result.cast<double>();
```

This uses the same C API operations as Part I (`PyImport_ImportModule`, attribute lookup, `PyObject_Call`), wrapped in C++.

---

### 11.7 pybind11 vs Hand-Written Python C API

The demo [`c_ext_pybind11_config`](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) exposes the same Python API as Part I [`c_ext_config_basic`](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic). The Python tests are intentionally parallel.

| Concern | Hand-written C API (Part I) | pybind11 (Part VII) |
|---|---|---|
| **Boilerplate** | `PyTypeObject`, getset, methods, module init | declarative `py::class_`, `m.def` |
| **Type safety** | C compiler on your structs | C++ compiler + templates on signatures |
| **Refcounting** | manual `Py_INCREF` / `Py_DECREF` | RAII `py::object`, `py::str`, … |
| **Errors** | `PyErr_SetString`, `return NULL` | C++ exceptions → Python (optional; `py::register_exception`) |
| **What you still own** | all semantics and ownership | return value policies, holder types, GIL release (`py::gil_scoped_release`) |
| **Debug surface** | your code is what runs | generated wrappers (harder to step through in a debugger) |
| **Language** | C | C++ required |

**Key message:** pybind11 **is** the C API — not a replacement runtime. It generates and wraps the same `PyObject*`, `PyTypeObject`, and method machinery Part I writes explicitly. Choose pybind11 when C++ is the implementation language and boilerplate cost dominates; choose hand-written C when you need minimal dependencies, C-only codebases, or maximum control over every slot.

---

### 11.8 Execution Path (Part II Tie-In)

Part II showed that `config.process()` on a hand-written extension resolves to **`PyCFunctionObject`** → direct C function pointer — no nested eval loop, no libffi.

pybind11-bound methods follow the **same path**: the wrapper pybind11 registers is still a `PyCFunction`-style callable. Contrast Part III:

| Call | Path |
|---|---|
| `config.process()` (Part I or VII) | `PyCFunctionObject` → direct C/C++ |
| `lib.add(2, 3)` (Part III ctypes) | `_FuncPtr` → `_ctypes` → libffi → `add` in `libadd.so` |

Both Part I and Part VII produce **`mymodule.cpython-<SOABI>.so`** modules that link against `libpython`. The difference is how the `.so` was authored — by hand or via pybind11 templates — not how Python dispatches the call once the module is loaded.

---

### 11.9 pybind11 vs ctypes — Compile Time vs Runtime

This is the central architectural split between Part VII and Parts III–V. [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html) §12.7 reframes it: pybind11 is **extension authoring** (compile-time); ctypes is **binding** through a bridge (runtime).

![Four approaches: ctypes, CFFI, hand-written extension, pybind11](/assets/images/python_c_ext_three_approaches.png)

| | pybind11 (Part VII) | ctypes (Parts III–V) |
|---|---|---|
| **User binding code** | C++ (`bindings.cpp`) | Python (`_fields_`, `argtypes`, wrapper classes) |
| **Bridge module imported** | **your** compiled `mymodule.cpython.so` | pre-built stdlib `_ctypes` |
| **When signatures are resolved** | compile time (templates) | runtime (libffi + metadata) |
| **Target code** | C++ compiled **into** the extension | existing plain `.so` via `dlopen` |
| **C++ classes** | native (`py::class_`, virtual, STL) | awkward — Part V handle pool exists as workaround |
| **`PyTypeObject` / attributes** | full (generated) | poor fit — Part IV mirrors layout only |
| **Rebuild per Python version** | yes (SOABI tag on your `.so`) | no for `_ctypes`; struct layout must still match C |
| **Per-call cost** | direct function pointer | libffi dispatch |

**ctypes model (runtime):**

```
Python user code  →  ctypes (Python)  →  _ctypes (ready-made C ext)  →  libffi  →  dlopen'd libfoo.so
```

User code is **Python**. Signatures come from `argtypes`/`restype` and `_fields_` at call time. The stdlib extension is already compiled.

**pybind11 model (compile time):**

```
C++ binding code  →  compiler + pybind11 headers  →  your mymodule.cpython.so  →  direct C++ calls
```

User code is **C++**. Signatures are read from C++ types at compile time. **You** ship a new C extension; there is no pre-built pybind11 module to `import` for your library.

Part IV's runtime layout section applies only to ctypes: `_ctypes` allocates a buffer matching `_fields_`. pybind11 never requires `_fields_` — the C++ object layout stays opaque; Python sees wrappers.

---

### 11.10 Comparison Across the Full Series

| | Part I C API | Part VII pybind11 | Part III–IV ctypes | Part V handle pool |
|---|---|---|---|---|
| **Token / type model** | `PyTypeObject` | generated `PyTypeObject` | `Structure` layout | `int64_t` handle |
| **User glue language** | C | C++ | Python | Python |
| **Build** | `setup.py` + C | `setup.py`/CMake + pybind11 | `make` target `.so` only | `make` + ctypes |
| **C++ support** | manual in C | first-class | via `extern "C"` shim | via `extern "C"` shim + pool |
| **Complex output** | return Python objects from C API | return `py::object` / bound types | out-param / return-by-value copy | out-param, by-value, or handle-return |
| **Callable path** | direct C | direct C++ | `_ctypes` + libffi | `_ctypes` + libffi |

**When to use pybind11:**

- New or existing **C++** codebase.
- Need Pythonic classes, methods, inheritance, STL, exceptions mapped to Python.
- Willing to compile and ship a per-Python-version extension module.
- Alternative to Part I when boilerplate cost is too high but you still need full `PyTypeObject` integration.

**When to stay with ctypes (Parts III–V):**

- Existing **plain C** shared library, stable C ABI.
- Stdlib-only integration, no binding compiler for end users.
- Quick runtime `dlopen` without rebuilding for each Python minor version.

**When to stay with hand-written C API (Part I):**

- C-only codebase, minimal dependencies, or you need explicit control over every `tp_*` slot and error path.

Part VI's `_rclpy_pybind11` and `rosidl` plain-`.so` typesupport modules illustrate both poles in one stack: pybind11 for the ROS client library API; plain shared objects + capsules for message conversion.

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) — §2.2.2 `Config` / `PyTypeObject`
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) — §5–§6 C extension dispatch
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) — §7.2 libffi, §7.4 three approaches
- [Part IV — Complex ctypes Structs](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) — §8 runtime layout, §8.10 comparison
- [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) — §9.11 series comparison
- [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) — `_rclpy_pybind11`
- [pybind11](https://github.com/pybind/pybind11) — [documentation](https://pybind11.readthedocs.io/en/latest/)
- [pybind11 — First steps](https://pybind11.readthedocs.io/en/latest/basics.html)
- [pybind11 — Object-oriented code](https://pybind11.readthedocs.io/en/latest/classes.html)
- [pybind11 — Cast overview](https://pybind11.readthedocs.io/en/latest/advanced/cast/overview.html)
- [pybind11 — Python C++ interface](https://pybind11.readthedocs.io/en/latest/advanced/pycpp/object.html)
- [pybind11 — Python objects as arguments](https://pybind11.readthedocs.io/en/latest/advanced/functions.html#python-objects-as-arguments)
- pybind11 source: [`include/pybind11/detail/class.h`](https://github.com/pybind/pybind11/blob/master/include/pybind11/detail/class.h) (`make_new_python_type`), [`cast.h`](https://github.com/pybind/pybind11/blob/master/include/pybind11/cast.h)
- Demo: [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config)
- Contrast: [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic)
- [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html)
