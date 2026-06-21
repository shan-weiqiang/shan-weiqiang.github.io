---
layout: post
title:  "Python C Extensions: Part V — ctypes Handle Pool"
date:   2026-06-20 10:00:00 +0800
tags: [python]
---

* toc
{:toc}

This article is Part V of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) covers hand-written extensions and `PyCapsule` opaque handles. [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) covers bytecode vs C method dispatch. [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) covers loading plain C libraries through `_ctypes` and libffi. [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) covers struct mirroring, keepalive, and the generalized handle idea behind `ctypes.Structure`. [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) applies the capsule pattern to ROS 2 `rosidl` Python bindings and `rclpy`. [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) covers compile-time C++ bindings as an alternative to the handle-pool pattern when you can compile a dedicated extension module. [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html) places this handle-pool design in the binding column of the series map.

Part V introduces a **layered handle-pool pattern** for binding **C++** through ctypes: an opaque **`int64_t` handle** indexes objects in a central **`HandlePool`**, a thin **`extern "C"` bridge** exposes stable symbols to `_ctypes`, and Python **wrapper classes** mirror each C++ type. The demo also shows **four ways to move complex data** across the C ABI — struct input, out-parameter output, return-by-value, and **handle-return** for complex results.

Runnable demo: [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding) in the [python](https://github.com/shan-weiqiang/python) repository.

```bash
make -C c_ext_handle_binding
python3 c_ext_handle_binding/test_handle_binding.py
```

| Section | Demo folder |
|---|---|
| §9.2–9.11 | [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding) — [`cpp/`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding/cpp), [`python/`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding/python), [`test_handle_binding.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/test_handle_binding.py) |
| §9.11 contrast (capsule) | [c_ext_capsule_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_capsule_config) (Part I §2.1) |
| §9.11 contrast (ctypes struct) | [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) (Part IV) |

---

## Section 9: ctypes Handle Pool for C++

### 9.1 Why a Handle Pool Behind ctypes

Part III showed ctypes calling scalar C functions in a plain `.so`. Part IV showed mirroring C structs with `ctypes.Structure`, keepalive, and user API classes above internal handles.

Those patterns work well for **plain C** and **transient** struct marshalling. They become awkward when:

- The backing implementation is **C++** with classes, virtual destructors, and `std::string` / containers.
- You need **long-lived objects** whose addresses must not cross the ctypes boundary (C++ ABI is not ctypes-safe).
- Several **distinct C++ types** share one FFI entry point and must be dispatched safely at runtime.
- Complex **results** should outlive a single FFI call without copying large structs on every access.

Part I's **`PyCapsule`** already solves opaque handles — but only inside a **hand-written C extension** (`Python.h`, `PyInit_*`). Part V keeps **stdlib-only Python glue** (ctypes) while adopting the same *idea*: an opaque token on the Python side, real object owned elsewhere.

The handle-pool pattern uses an **`int64_t` integer** as the token (Wikipedia's [handle](https://en.wikipedia.org/wiki/Handle_(computing)) model). Value `0` means invalid. The pool maps `1, 2, 3, …` to `std::unique_ptr<HandleObject>` instances. Python never sees C++ pointers.

---

### 9.2 Three-Layer Architecture

The demo splits responsibilities into three layers. Each layer has a narrow job; extension means adding types, not rewriting the core.

![ctypes handle pool three-layer architecture](/assets/images/python_c_ext_handle_pool_layers.png)

| Layer | Location | Responsibility |
|---|---|---|
| **C++** | `cpp/*.hpp`, `cpp/*.cpp` | Business logic, `HandleObject` interface, `HandlePool` storage and lifecycle |
| **C ABI** | `cpp/bridge.cpp` | `extern "C"` functions only — stable ctypes surface, no `Python.h` |
| **Python** | `python/*.py` | `CDLL` load, `argtypes`/`restype`, `HandleResource` base, per-type wrappers |

**Directory layout:**

```
c_ext_handle_binding/
├── cpp/
│   ├── types.hpp                  # HandleId, TypeId enum
│   ├── handle_object.hpp          # abstract HandleObject
│   ├── handle_pool.hpp/.cpp       # store / get / release / get_as
│   ├── c_types.h                  # C structs for ctypes (ConfigSpec, …)
│   ├── config.hpp/.cpp            # demo business type 1
│   ├── counter.hpp/.cpp           # demo business type 2
│   ├── *_resource.hpp/.cpp        # complex result types stored as handles
│   └── bridge.cpp                 # extern "C" exports
├── python/
│   ├── _native.py                 # CDLL + signatures + error helpers
│   ├── handle.py                  # HandleResource base
│   ├── types.py                   # ctypes.Structure mirrors
│   ├── config.py, counter.py      # business wrappers
│   └── *_resource.py              # wrappers for handle-returned results
├── Makefile                       # g++ -shared → libhandle_bridge.so
└── test_handle_binding.py
```

Build produces **`libhandle_bridge.so`** — a plain shared library, **not** a `mymodule.cpython-….so` C extension. Python loads it with `ctypes.CDLL`, same class of dynamic linking as Part III §7.2.

---

### 9.3 C++ Layer: HandleObject and HandlePool

**Full sources:** [handle_object.hpp](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/handle_object.hpp), [handle_pool.hpp](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/handle_pool.hpp), [types.hpp](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/types.hpp)

Every C++ instance managed by the pool implements a minimal abstract interface:

```cpp
class HandleObject {
public:
    virtual ~HandleObject() = default;
    virtual TypeId type() const = 0;
};
```

No business logic in the base class — `Config::process()`, `Counter::increment()`, and so on stay in concrete types. The base exists so the pool can store heterogeneous objects and delete them through a virtual destructor.

`TypeId` is an explicit enum (no RTTI across the C ABI):

```cpp
enum class TypeId : int {
    Config = 1,
    Counter = 2,
    ConfigSnapshot = 3,
    ProcessSummary = 4,
    CounterStats = 5,
};
```

**`HandlePool`** owns all objects:

```cpp
class HandlePool {
public:
    HandleId store(std::unique_ptr<HandleObject> obj);
    HandleObject* get(HandleId handle);
    bool release(HandleId handle);
    int type_of(HandleId handle) const;

    template <typename T>
    T* get_as(HandleId handle, TypeId expected);
private:
    HandleId next_id_ = 1;
    std::unordered_map<HandleId, std::unique_ptr<HandleObject>> handles_;
};
```

- **`store`** assigns the next monotonic id (starting at `1`), moves the `unique_ptr` into the map, returns the id.
- **`release`** erases the entry; destroying the `unique_ptr` runs the concrete destructor.
- **`get_as<T>`** — lookup plus type check (§9.9).

Demo **business types**: `Config` (mirrors Part I §2.1 capsule semantics), `Counter` (simple mutable counter).

Demo **result resource types**: `ConfigSnapshotResource`, `ProcessSummaryResource`, `CounterStatsResource` — C++ objects that *hold* complex data and are returned to Python as **new handles** (§9.8).

A single process-wide pool lives in `bridge.cpp` (`static HandlePool g_pool`). ctypes has no pool-handle parameter; one library, one pool. A future extension could pass pool ids if multiple pools are needed.

---

### 9.4 C ABI Bridge: extern "C" Without Python.h

**Full source:** [bridge.cpp](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/bridge.cpp), [c_types.h](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/c_types.h)

ctypes requires **C-linkable** symbols. The bridge file wraps C++ in `extern "C"` blocks. C++ classes, templates, and name-mangled symbols never cross the boundary.

**Shared pool API:**

```c
void        handle_release(int64_t handle);
int         handle_type(int64_t handle);       /* TypeId or -1 */
const char* handle_last_error(void);
```

**Per-type APIs** follow a consistent naming pattern: `config_create`, `config_process`, `counter_create`, `counter_increment`, …

**Error model:** ctypes cannot raise Python exceptions from C without `Python.h`. The bridge uses:

- `thread_local std::string g_last_error` + `handle_last_error()`
- Sentinel returns: `0` for invalid handle, `-1` for failed `int` status

Python checks return values and raises `RuntimeError`:

```python
def _check_handle(handle: int) -> int:
    if handle == 0:
        raise RuntimeError(_last_error())
    return handle
```

**C structs** shared by C and ctypes live in [`c_types.h`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/c_types.h) with `extern "C"` guards — plain C layout, no C++ features:

```c
typedef struct ConfigSpec {
    int32_t timeout;
    int32_t enable_ssl;
    char server_url[HANDLE_BRIDGE_URL_MAX];
} ConfigSpec;
```

---

### 9.5 Python Layer: CDLL, HandleResource, Typed Wrappers

**Full sources:** [_native.py](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/_native.py), [handle.py](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/handle.py), [config.py](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/config.py)

**Load the library** (path relative to package):

```python
_LIB_PATH = Path(__file__).resolve().parent.parent / "libhandle_bridge.so"
_lib = ctypes.CDLL(str(_LIB_PATH))
```

Register every symbol ([function prototypes](https://docs.python.org/3/library/ctypes.html#function-prototypes)):

```python
_lib.config_create.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_lib.config_create.restype = ctypes.c_int64
```

**`HandleResource`** is the base class every wrapper inherits:

```python
class HandleResource:
    def __init__(self, handle: int) -> None:
        if handle == 0:
            raise ValueError("invalid handle")
        self._handle = handle
        self._closed = False

    def close(self) -> None:
        if self._closed or self._handle == 0:
            return
        _lib.handle_release(self._handle)
        self._handle = 0
        self._closed = True

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def __del__(self): self.close()
```

**Typed wrappers** (`Config`, `Counter`, …) expose `classmethod create(...)` factories that call the C create function, check the handle, and return `cls(handle)`. Methods pass `self.handle` into C operation functions.

![handle pool create operate release lifecycle](/assets/images/python_c_ext_handle_pool_lifecycle.png)

---

### 9.6 Complex Types as Input (Accept Structs)

Part IV focused on passing structs **into** C. The handle-pool demo uses the same ctypes machinery for **creation** and **mutation** APIs.

| C API | Role |
|---|---|
| `config_create_from_spec(const ConfigSpec*)` | Create `Config` from struct input |
| `counter_apply_delta(int64_t, const DeltaSpec*)` | Apply repeated delta from struct |
| `config_spec_merge(left, right, out)` | Pure C helper — no handle, struct in/out |

Python mirrors C structs in [types.py](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/types.py):

```python
class ConfigSpec(ctypes.Structure):
    _fields_ = [
        ("timeout", ctypes.c_int32),
        ("enable_ssl", ctypes.c_int32),
        ("server_url", ctypes.c_char * HANDLE_BRIDGE_URL_MAX),
    ]
```

Factory usage:

```python
spec = make_config_spec(30, "http://server.com", True)
config = Config.create_from_spec(spec)
```

Pass with [`byref`](https://docs.python.org/3/library/ctypes.html#ctypes.byref):

```python
_lib.config_create_from_spec.argtypes = [ctypes.POINTER(ConfigSpec)]
handle = _lib.config_create_from_spec(ctypes.byref(spec))
```

Embedded `char[]` fields avoid the keepalive problems of `char*` in Part IV §8.5 — the struct owns the bytes. Pointer-string patterns from Part IV still apply if you add `char*` fields later.

---

### 9.7 Complex Types as Output — Out-Parameter and Return-by-Value

Two patterns that do **not** add a new pool entry:

#### Out-parameter (caller allocates struct, C fills)

```c
int config_get_snapshot(int64_t handle, ConfigSnapshot* out);
```

Python allocates `ConfigSnapshot()` on the stack, passes `ctypes.byref(out)`, reads fields into a view dataclass:

```python
def snapshot(self) -> ConfigSnapshotView:
    out = ConfigSnapshot()
    _check_status(_lib.config_get_snapshot(self.handle, ctypes.byref(out)))
    return snapshot_to_view(out)
```

Lifetime: the output exists only in Python for that call. No handle is returned.

#### Return-by-value (C returns struct copy)

```c
ProcessSummary config_process_summary(int64_t handle);
```

ctypes copies the struct across the FFI boundary when `restype` is set:

```python
_lib.config_process_summary.argtypes = [ctypes.c_int64]
_lib.config_process_summary.restype = ProcessSummary

summary = _lib.config_process_summary(self.handle)
```

This works for **small POD structs**. Large or heap-backed results are a poor fit — every read pays a full copy, and pointer fields inside the struct reintroduce Part IV ownership issues.

---

### 9.8 Complex Types as Output — Handle-Return Pattern

The third output pattern stores the result as a **new `HandleObject`** in the pool and returns its **integer handle**. Python constructs a dedicated wrapper class from that handle.

![three complex return patterns compared](/assets/images/python_c_ext_complex_return_patterns.png)

| | Out-parameter | Return-by-value | **Handle-return** |
|---|---|---|---|
| C returns | `int` status; fills `*out` | `ProcessSummary` struct | `int64_t` new handle |
| Python gets | dataclass view | dataclass view | `ProcessSummaryResource(handle)` |
| C++ lifetime | no pool entry | copy at FFI boundary | pool owns until `handle_release` |
| Best for | small snapshots | small POD reads | results you query repeatedly; C++-backed state |


---

### 9.9 Type Safety: TypeId and get_as

Every operation that dereferences a handle must validate **existence** and **type**. Wrong-type handles are a common FFI bug (passing a `Config` handle where `Counter` is expected).

`HandlePool::get_as` centralizes the check:

```cpp
template <typename T>
T* get_as(HandleId handle, TypeId expected) {
    HandleObject* obj = get(handle);
    if (obj == nullptr || obj->type() != expected) {
        return nullptr;
    }
    return static_cast<T*>(obj);
}
```

Each concrete class implements `type()`:

```cpp
TypeId Config::type() const { return TypeId::Config; }
```

Bridge functions use one error path:

```cpp
Config* config = g_pool.get_as<Config>(handle, TypeId::Config);
if (config == nullptr) {
    set_error("invalid handle or wrong type");
    return -1;
}
```

**Three failure modes**, same message:

1. **Invalid handle** — never existed, or already `handle_release`d.
2. **Wrong `TypeId`** — e.g. `counter_increment(config_handle, 1)` when `config_handle` points at a `Config`.
3. **Null out-pointer** on read APIs — `config_get_snapshot(handle, nullptr)`.

The test proves cross-type misuse fails:

```python
config = Config.create(30, "http://server.com", True)
result = _lib.counter_increment(config.handle, 1)
assert result == -1
assert b"invalid handle or wrong type" in _lib.handle_last_error()
```

**Design notes:**

- No `dynamic_cast` / RTTI — the C ABI does not carry C++ type information; `TypeId` is the explicit contract.
- `static_cast` after `type()` check is safe because only the pool creates objects and each class reports a fixed `TypeId`.
- Python can query `handle_type(handle)` or `wrapper.type_id` for debugging; wrappers should still rely on typed C APIs, not blind casts.

---

### 9.10 Extending the Framework

Adding a new C++ type (e.g. `Buffer`) without changing `HandlePool` or `HandleResource`:

1. Add `TypeId::Buffer` in [`types.hpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/types.hpp).
2. Implement `class Buffer : public HandleObject` in new `buffer.hpp` / `buffer.cpp`.
3. Add `buffer_create` / `buffer_*` functions in [`bridge.cpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/cpp/bridge.cpp) (or split per-type bridge files as the project grows).
4. Append sources to [`Makefile`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/Makefile) `SOURCES`.
5. Register `argtypes` / `restype` in [`_native.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/_native.py).
6. Add `Buffer(HandleResource)` in new `buffer.py`; export from [`__init__.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_binding/python/__init__.py).

For complex **results**, add a `BufferViewResource : HandleObject` and `buffer_create_view(source_handle)` returning a new handle — same handle-return pattern as §9.8.

---

### 9.11 Comparison Across the Series

| | Part I `PyCapsule` | Part IV `ctypes.Structure` | Part V handle pool | Part VII pybind11 |
|---|---|---|---|---|
| **Token** | capsule object | `Structure` instance | `int64_t` handle | generated `PyTypeObject` |
| **Owner** | capsule destructor | Python GC + keepalive | `HandlePool` + `handle_release` | holder in extension |
| **Language** | C struct in C extension | plain C `.so` | C++ classes + virtual interface | C++ in extension |
| **Python glue** | `Python.h` / `PyInit_*` | ctypes only | ctypes only | none (import extension) |
| **Multi-type dispatch** | capsule name string | N/A (layout only) | `TypeId` + `get_as` | `py::class_` per type |
| **Complex input** | `PyArg_ParseTuple` | `Structure` + `byref` | `Structure` + `byref` (same as IV) | C++ parameters / casters |
| **Complex output** | return Python objects from C API | out-param / return-by-value copy | out-param, by-value, **or handle-return** | return `py::object` / bound types |
| **User API** | module functions | `InputRecordPy`, `transform()` | `Config`, `Counter`, `*Resource` | native module API |

**When to use Part V:**

- Existing or new **C++** codebase behind a stable C ABI.
- You want **ctypes-only** Python integration (no per-library `PyInit_*`).
- Multiple C++ types share one `.so` and need **typed** handle dispatch.
- Complex results should live as **pool-managed objects** with explicit `close()` / context managers.

**When to prefer Part I instead:** tight integration with Python's object model (`PyTypeObject`, attributes, exceptions as first-class types) — or **Part VII pybind11** for the same integration with C++ and less boilerplate.

**When to prefer Part VII instead of Part V:** you can compile a dedicated extension module and want native C++ classes without a C ABI shim or handle pool.

**When to prefer Part IV alone:** plain C library, transient struct marshalling, no long-lived C++ objects.

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) — §2.1 `PyCapsule` opaque handle
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html)
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) — §7.2 scalar ctypes, libffi
- [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) — §8 struct mirroring, §8.11 handle concept
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html)
- [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html)
- [ctypes — Python 3 documentation](https://docs.python.org/3/library/ctypes.html)
- [ctypes — Structures and unions](https://docs.python.org/3/library/ctypes.html#structures-and-unions)
- [ctypes — Function prototypes](https://docs.python.org/3/library/ctypes.html#function-prototypes)
- [ctypes — `byref`](https://docs.python.org/3/library/ctypes.html#ctypes.byref)
- [Handle (computing)](https://en.wikipedia.org/wiki/Handle_(computing))
- Demo: [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding)
- Capsule contrast: [c_ext_capsule_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_capsule_config)
