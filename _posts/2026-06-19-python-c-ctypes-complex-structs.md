---
layout: post
title:  "Python C Extensions: Part IV — ctypes Structs and Handles"
date:   2026-06-19 19:30:00 +0800
tags: [python]
---

* toc
{:toc}

This article is Part IV of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) covers hand-written C extensions and binding C data to Python types. [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) covers bytecode and C method dispatch. [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) showed calling a plain C library with scalar `add(int, int)`. [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) builds a C++ `HandlePool` with integer handles and typed dispatch behind ctypes.

Part IV covers **how to handle complex C structures with ctypes**: nested structs, fixed-size arrays, embedded `char[]` vs `char*`, pointer fields, marshalling through `_ctypes` + libffi, and **keepalive** for anything whose address crosses the boundary. It closes with **handles** — internal separation layers between your **user API** and C-managed resources ([Wikipedia](https://en.wikipedia.org/wiki/Handle_(computing)): file descriptors, `PyCapsule`, `ctypes.Structure`, buffer addresses, …). The demo’s `InputRecordPy` / `OutputRecordPy` are **user API** classes (§8.9), not handles themselves. Struct names in the demo are arbitrary fixtures for the binding patterns.

You still write Python-only glue (no new `PyInit_*` module); the new work is layout fidelity and lifetime management.

Runnable demo: [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) in the [python](https://github.com/shan-weiqiang/python) repository.

```bash
make -C ctypes_complex_struct
python3 ctypes_complex_struct/test_struct_demo.py
```

| Section | Demo folder |
|---|---|
| §8.2–8.11 | [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) — [`struct_demo.h`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/struct_demo.h), [`bindings.py`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/bindings.py), [`test_struct_demo.py`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/test_struct_demo.py) |

---

## Section 8: ctypes with Complex Structs

### 8.1 Beyond Scalar Arguments

Part III’s ctypes example calls one function with two integers:

```python
lib.add.argtypes = [ctypes.c_int, ctypes.c_int]
lib.add.restype = ctypes.c_int
assert lib.add(2, 3) == 5
```

Most real C APIs also use **structs**: a function takes a pointer to an input struct (and maybe scalars), and returns a struct or fills an output struct. The hard part is not `dlopen` — Part III already covered that — but expressing the C layout in Python and keeping pointer targets alive across the call.

The demo library exposes one such function so every pattern appears in a single test:

```c
OutputRecord transform_record(
    const InputRecord *input,
    double scale,
    int min_weight,
    int top_n
);
```

ctypes maps each C struct to a `ctypes.Structure` subclass. `_ctypes` passes a pointer to the input through libffi (same machinery as Part III §7.2). That `Structure` instance is a **handle** in the broad sense (§8.11): it separates binding code from raw C memory. Application code should sit above that in a **user API** (§8.9) that owns the handles internally.

---

### 8.2 C Layout Patterns in the Demo

**Full header:** [struct_demo.h](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/struct_demo.h)

The header is intentionally dense: one small nested type, then input/output structs that combine the field kinds you typically mirror in ctypes. Names like `Metric` or `InputRecord` are arbitrary; focus on the **field kinds**:

| Pattern | Example in header |
|---|---|
| Nested struct | `Point anchor` inside `Metric` |
| Fixed array of structs | `Metric metrics[MAX_METRICS]`, `Point corners[2]` |
| Fixed array of scalars | `int weights[MAX_WEIGHTS]` |
| 2D embedded char buffers | `char categories[MAX_TAGS][MAX_LABEL]` |
| Pointer to NUL-terminated string | `char *description`, `char *tags[]` |
| Pointer to struct | `Metric *metric_ptrs[MAX_PTRS]` |
| C-allocated output pointers | `char *notes`, `Metric *ranked_ptrs[]` in `OutputRecord` |

Nested types and shared caps (must match Python):

```c
#define MAX_METRICS   4
#define MAX_LABEL     32
/* ... */

typedef struct {
    int x;
    int y;
} Point;

typedef struct {
    char  label[MAX_LABEL];
    int   weight;
    Point anchor;
} Metric;
```

Input struct — embedded arrays plus pointer fields:

```c
typedef struct {
    char   header_id[MAX_LABEL];
    int    version;
    Point  origin;
    Point  corners[2];
    Metric metrics[MAX_METRICS];
    int    weights[MAX_WEIGHTS];
    char   categories[MAX_TAGS][MAX_LABEL];
    char  *description;
    char  *tags[MAX_TAGS];
    int    tag_count;
    Metric *metric_ptrs[MAX_PTRS];
    int    metric_ptr_count;
} InputRecord;
```

Output struct — same ideas on the return side, including pointers the C function may `malloc`:

```c
typedef struct {
    char   title[MAX_LABEL];
    Point  bbox[2];
    int    total_weight;
    int    filtered_weights[MAX_WEIGHTS];
    int    filtered_weight_count;
    Metric top_metrics[MAX_PTRS];
    char   summary_lines[MAX_SUMMARY][MAX_LABEL];
    char  *notes;
    Metric *ranked_ptrs[MAX_PTRS];
    int    ranked_ptr_count;
} OutputRecord;
```

[`struct_demo.c`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/struct_demo.c) reads and writes every field category above (embedded arrays, pointer strings, pointer-to-struct arrays, heap output). [`test_struct_demo.py`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/test_struct_demo.py) asserts the round trip. You do not need the business logic — only that the C side touches each pattern so the bindings stay honest.

`free_output_record` frees heap fields (`notes`, `ranked_ptrs[]`) allocated inside `transform_record` — a second ctypes concern: **output ownership** (§8.8).

---

### 8.3 Mapping C to `ctypes.Structure`

**Full bindings:** [bindings.py](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/bindings.py)

**Rule 1:** Python `MAX_*` constants match the header.

**Rule 2:** Each `ctypes.Structure` subclass lists `_fields_` in the **same order** as the C struct. Wrong order or wrong ctypes type corrupts memory or crashes — there is no compile-time check ([structure alignment](https://docs.python.org/3/library/ctypes.html#structure-alignment-and-byte-order)).

Start with leaf structs, then compose:

```python
class Point(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
    ]


class Metric(ctypes.Structure):
    _fields_ = [
        ("label", ctypes.c_char * MAX_LABEL),
        ("weight", ctypes.c_int),
        ("anchor", Point),
    ]
```

`InputRecord` and `OutputRecord` in Python mirror the C definitions field-for-field (see [Structures and unions](https://docs.python.org/3/library/ctypes.html#structures-and-unions)):

```python
class InputRecord(ctypes.Structure):
    _fields_ = [
        ("header_id", ctypes.c_char * MAX_LABEL),
        ("version", ctypes.c_int),
        ("origin", Point),
        ("corners", Point * 2),
        ("metrics", Metric * MAX_METRICS),
        ("weights", ctypes.c_int * MAX_WEIGHTS),
        ("categories", (ctypes.c_char * MAX_LABEL) * MAX_TAGS),
        ("description", ctypes.c_char_p),
        ("tags", ctypes.c_char_p * MAX_TAGS),
        ("tag_count", ctypes.c_int),
        ("metric_ptrs", ctypes.POINTER(Metric) * MAX_PTRS),
        ("metric_ptr_count", ctypes.c_int),
    ]
```

Load the shared library built by `make`:

```python
_LIB_PATH = Path(__file__).with_name("libstruct_demo.so")
_lib = ctypes.CDLL(str(_LIB_PATH))
```

---

### 8.4 Nested Structs and Fixed Arrays

| C pattern | ctypes |
|---|---|
| `Point anchor` inside `Metric` | `("anchor", Point)` |
| `Point corners[2]` | `("corners", Point * 2)` |
| `Metric metrics[MAX_METRICS]` | `("metrics", Metric * MAX_METRICS)` |
| `int weights[MAX_WEIGHTS]` | `("weights", ctypes.c_int * MAX_WEIGHTS)` |
| `char categories[MAX_TAGS][MAX_LABEL]` | `("categories", (ctypes.c_char * MAX_LABEL) * MAX_TAGS)` |

Assign nested structs by value:

```python
record.origin = self.origin.to_ctypes()
record.corners[i] = corner.to_ctypes()
record.metrics[i] = metric.to_ctypes()
```

For a 2D char array slot, direct assignment to `categories[i]` is awkward; the demo uses `from_address` on the struct’s memory:

```python
slot = (ctypes.c_char * MAX_LABEL).from_address(
    ctypes.addressof(struct) + field_type.offset + index * MAX_LABEL
)
```

That writes bytes into the correct offset inside the parent struct without guessing layout beyond what ctypes already knows.

---

### 8.5 Strings: Embedded `char[]` vs `char*`

Two common C patterns need different ctypes handling:

**Embedded buffers** (`header_id`, `label`, `title`): field type is `c_char * N`. Assign UTF-8 bytes (with a length guard):

```python
def _encode_label(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) >= MAX_LABEL:
        raise ValueError(f"label too long (max {MAX_LABEL - 1} bytes): {value!r}")
    return encoded

_write_label_field(record, "header_id", self.header_id)
```

**Pointer strings** (`description`, each `tags[i]`): C expects `char *` to NUL-terminated data. Use [`create_string_buffer`](https://docs.python.org/3/library/ctypes.html#ctypes.create_string_buffer) and pass the buffer address:

```python
description_buf = ctypes.create_string_buffer(self._description.encode("utf-8"))
record.description = ctypes.c_char_p(ctypes.addressof(description_buf))
```

**Keepalive (critical):** anything whose address you pass to C must stay alive until the C call returns. Buffers, `c_char_p` wrappers, standalone `Metric` structs, and `POINTER(Metric)` values are all ordinary Python objects — the GC can collect them if nothing references them.

`to_ctypes()` returns `(record, keepalive)`:

```python
keepalive: list[object] = []
# ... append description_buf, record.description, tag buffers, metric structs, pointers ...
keepalive.append(record)
return record, keepalive
```

`transform()` must hold the list through the call:

```python
c_input, keepalive = input_record.to_ctypes()
_ = keepalive  # must survive through the C call
c_output = _lib.transform_record(ctypes.byref(c_input), ...)
```

If `keepalive` is dropped while C still reads those addresses, you get use-after-free — silent corruption or a crash.

---

### 8.6 Arrays of Pointers (`Metric*`)

When C has `Metric *metric_ptrs[MAX_PTRS]` — an array of **pointers** to structs, not an embedded array — ctypes uses:

```python
("metric_ptrs", ctypes.POINTER(Metric) * MAX_PTRS),
```

Build each entry from a standalone struct and a pointer object; keep both:

```python
metric_obj = metric.to_ctypes()
metric_storage.append(metric_obj)
metric_ptr = ctypes.pointer(metric_storage[-1])
record.metric_ptrs[i] = metric_ptr
keepalive.extend([metric_storage[-1], metric_ptr])
```

Read back through `.contents`:

```python
MetricPy.from_ctypes(record.metric_ptrs[i].contents)
```

---

### 8.7 Binding the Function

![ctypes complex struct call flow](/assets/images/python_c_ext_ctypes_struct_flow.png)

```python
_lib.transform_record.argtypes = [
    ctypes.POINTER(InputRecord),
    ctypes.c_double,
    ctypes.c_int,
    ctypes.c_int,
]
_lib.transform_record.restype = OutputRecord

_lib.free_output_record.argtypes = [ctypes.POINTER(OutputRecord)]
_lib.free_output_record.restype = None
```

Pass the input with [`byref`](https://docs.python.org/3/library/ctypes.html#ctypes.byref) (cheaper than `pointer()` for a one-shot call):

```python
c_output = _lib.transform_record(
    ctypes.byref(c_input),
    ctypes.c_double(scale),
    ctypes.c_int(min_weight),
    ctypes.c_int(top_n),
)
```

`restype = OutputRecord` means the C **return-by-value** struct is copied into a new Python `Structure` instance. Pointer fields inside that copy (`notes`, `ranked_ptrs[]`) still point at C heap memory from the temporary C return value — you must read them before freeing, and you must call `free_output_record` on the Python copy’s backing layout (see §8.8).

Wrong `_fields_` or `argtypes` still corrupts the stack or misreads memory — same runtime-only safety as Part III §7.2.

---

### 8.8 Output Ownership and Cleanup

When C **allocates** memory reachable through struct pointer fields (`strdup`, `malloc` into `output.notes`, `output.ranked_ptrs[i]`, …), Python must call a matching free function. The demo exposes `free_output_record`; your real library will have its own name.

Pattern: wrap the returned `Structure` and call free from `close()` / `__exit__`:

```python
def close(self) -> None:
    if self._closed:
        return
    _lib.free_output_record(ctypes.byref(self._record))
    self._closed = True

def __enter__(self) -> OutputRecordPy:
    return self

def __exit__(self, exc_type, exc, tb) -> None:
    self.close()
```

End-to-end test ([`test_struct_demo.py`](https://github.com/shan-weiqiang/python/blob/main/ctypes_complex_struct/test_struct_demo.py)) builds input through the **user API**, calls `transform`, and checks scalars, embedded fields, and ranked pointer output:

```python
inp = InputRecordPy("sensor-A", version=2, origin=(10, 20))
inp.set_corner(0, (0, 0))
inp.set_corner(1, (100, 50))
inp.add_metric(MetricPy("cpu", 80, (1, 2)))
inp.add_metric(MetricPy("io", 90, (5, 6)))
inp.set_weight(0, 10)
inp.set_weight(1, 20)
inp.set_weight(2, 30)
inp.add_tag("critical")
inp.add_metric_ptr(MetricPy("net", 70, (7, 8)))

with transform(inp, scale=1.5, min_weight=20, top_n=2) as out:
    assert out.total_weight == int((10 + 20 + 30) * 1.5)
    assert out.filtered_weights() == [30, 45]
    top = out.top_metrics()
    assert top[0].label == "io"   # highest weight across embedded + pointer metrics
```

The string values are arbitrary; the test proves each **field category** round-trips. After the `with` block, `free_output_record` has run — do not use `out` again.

---

### 8.9 Demo User API: `InputRecordPy` and `OutputRecordPy`

ctypes does not require `InputRecordPy`, `MetricPy`, or `PointPy`. In the demo they are the **user API** — the surface application code is meant to call. They are **not** handles; they sit on the user side and **use handles internally** (`InputRecord`, keepalive buffers, `POINTER(Metric)`, …) when crossing into C.

- **`InputRecordPy`**: methods like `add_metric`, `set_weight`, `add_tag` build logical input. `to_ctypes()` (inside `transform`) assembles the `InputRecord` handle and keepalive list — callers never see those objects.
- **`OutputRecordPy`**: methods like `filtered_weights()`, `top_metrics()` read results. `close()` / the context manager calls `free_output_record` on the internal `OutputRecord` handle.

```python
inp = InputRecordPy("sensor-A", version=2, origin=(10, 20))
inp.add_metric(MetricPy("cpu", 80, (1, 2)))
# inp: user API — no InputRecord or keepalive visible

with transform(inp, scale=1.5, min_weight=20, top_n=2) as out:
    # out: user API — reads results; bindings free C heap on exit
    assert out.filtered_weights() == [30, 45]
```

Without this user API every caller would assemble `_fields_`, manage keepalive, pass `byref`, and call `free_output_record` themselves — mixing application logic with handle management. The binding module centralizes handle work behind `transform()` and these classes.

---

### 8.10 ctypes Structs vs Hand-Written Extensions vs CFFI

| | ctypes `Structure` | CFFI `ffi.new` (Part III §7.5) | Hand-written extension (Part I) |
|---|---|---|---|
| **Layout definition** | Python `_fields_` | `cdef` pasted from header | C struct + `PyTypeObject` |
| **User-facing API** | user API classes (§8.9) over internal handles | `ffi` struct objects | native attributes / methods |
| **Pointer / buffer safety** | manual keepalive | manual keepalive | C API / object ownership |
| **Build step** | `make` for target `.so` only | ABI or API CFFI build | `setup.py` C extension |
| **Callable path** | `_ctypes` + libffi | `_cffi_backend` + libffi or generated `.so` | direct C in `mymodule.so` |

**Use ctypes struct mirroring** when you have a stable C header and an existing shared library and want stdlib-only glue — the techniques in §8.3–8.8 apply regardless of what the structs represent.

**Prefer a hand-written extension (Part I)** when you need types integrated with Python’s attribute protocol, exceptions, and object identity as first-class module API.

**Consider CFFI** when you want header-driven layout (`cdef`) or compile-time checks in API mode; see [CFFI struct/array example](https://cffi.readthedocs.io/en/stable/overview.html#struct-array-example-minimal-in-line) and Part III §7.5.

---

### 8.11 Handles: A Generalized View

Sections §8.3–8.8 are about **layout** at the FFI boundary. This section names the **unifying idea** behind capsules, ctypes structs, file descriptors, and keepalive buffers: the [handle](https://en.wikipedia.org/wiki/Handle_(computing)) in computer programming — and how that differs from the **user API** in §8.9.

#### What “handle” means

Wikipedia defines a handle as an **abstract reference to a resource** used when software refers to memory or objects **managed by another system** (operating system, runtime, C library, …). The key property is **separation**: something on the user side holds a token; another layer owns or mediates the real resource.

A handle is **not** the user API itself (`InputRecordPy.add_metric` is API, not a handle). It is **any internal layer that separates the user API from the resource** — opaque integer, pointer, capsule, `Structure`, string buffer address, …:

| Handle (examples) | Separates user API from | Typical form |
|---|---|---|
| File descriptor | Kernel file / socket object | Integer (often opaque index) |
| `FILE *` / C `FILE` | OS file representation | Pointer or struct |
| `HWND` (Windows) | Desktop window object | Typed pointer / integer ID |
| Part I `PyCapsule` | `struct ComplexConfig *` in C heap | Python capsule object |
| `ctypes.Structure` (`InputRecord`) | C struct layout + field addresses | Python `Structure` instance |
| `create_string_buffer` + `c_char_p` | NUL-terminated bytes in Python heap | Buffer + pointer wrapper |
| `POINTER(Metric)` in keepalive | Standalone metric struct address | ctypes pointer object |

A **file descriptor** is a handle even though it is “just an int”: its value is interpreted only by the kernel’s file table. A **`ctypes.Structure`** is a handle inside the binding module: the user API calls `to_ctypes()`, not `record.metrics[i] = …` on a raw struct. A **PyCapsule** is a handle because Python cannot inspect the C struct inside; only the extension dereferences it.

#### User API vs handles

| | User API | Handle |
|---|---|---|
| **Who uses it** | Application / test code | Binding code (module-internal) |
| **Demo examples** | `InputRecordPy`, `transform()`, `out.filtered_weights()` | `InputRecord`, keepalive list, `OutputRecord` on `self._record` |
| **Role** | Express intent (`add_metric("cpu", 80, …)`) | Mediate access to C-managed memory |
| **Should leak to callers?** | yes — that is the public contract | no — hide behind user API |

Handles can **stack** below the user API. In the demo:

```
application code          user API (what you call)
    → InputRecordPy.add_metric(…), transform(inp)
        → InputRecord + keepalive buffers     handles (binding-internal)
        → byref → _ctypes → libffi            handles (runtime FFI)
        → transform_record in libstruct_demo.so   resource (C memory / logic)
```

`OutputRecordPy` is user API; the `OutputRecord` stored on `self._record` is the handle it holds until `free_output_record` runs.

#### Handles vs pointers

[Wikipedia](https://en.wikipedia.org/wiki/Handle_(computing)) contrasts handles with pointers: a pointer **is** the address of the referent; a handle is an abstraction **managed externally**. ctypes uses real pointer types (`POINTER(Metric)`), but they live inside the binding layer. The user API never exposes `metric_ptrs[i]` — only `add_metric_ptr(MetricPy(...))`.

#### Binding responsibilities (behind the user API)

Module-internal code that owns handles typically:

1. **Marshals** — fill `Structure` fields, buffers, `pointer()` values in `to_ctypes()`.
2. **Unmarshals** — decode `c_char` arrays and `c_char_p` in user API methods.
3. **Manages lifetime** — keepalive through the C call; `free_output_record` in `OutputRecordPy.close()`:

```python
class OutputRecordPy:
    def __init__(self, record: OutputRecord):
        self._record = record  # handle to C-backed output struct
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        _lib.free_output_record(ctypes.byref(self._record))
        self._closed = True
```

Users call `out.filtered_weights()`; they do not call `free_output_record` — that is handle management inside the binding.

#### Same idea across this article series

| Part | User API (examples) | Handle (examples) | Resource |
|---|---|---|---|
| OS | `read(fd, …)` | file descriptor | kernel file object |
| Part I §2.1 | `process_config(capsule)` | `PyCapsule` | C `ComplexConfig *` |
| Part III §7.2 | `lib.add(2, 3)` | `_FuncPtr` / `CDLL` binding | `add` in `libadd.so` |
| Part IV demo | `InputRecordPy`, `transform()` | `InputRecord`, keepalive | C structs in `libstruct_demo.so` |
| Part V handle pool | `Config`, `Counter`, `*Resource` | `int64_t` handle | C++ objects in `HandlePool` |

Same structural role for handles: token on the API side, mediator, resource on the other side. The **user API** is whichever functions and classes you publish; handles stay internal unless you deliberately expose low-level access. Part V makes the pool and `TypeId` check explicit for C++ behind ctypes (see [Part V §9.8–9.9](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html)).

#### Practical guidance

- Keep **ctypes `Structure` subclasses** module-internal — they are handles at the FFI boundary.
- Keep **buffers, `c_char_p`, `POINTER(...)`** inside `to_ctypes()` / keepalive — also handles.
- Expose a **user API** (`InputRecordPy`, `transform`, …) that owns handle assembly and cleanup.
- **Handle leaks** ([Wikipedia](https://en.wikipedia.org/wiki/Handle_(computing))) still apply: forgetting `out.close()` leaves C heap memory allocated, like forgetting `close(fd)`.

`transform(inp: InputRecordPy, ...)` takes user API on input; inside it builds `InputRecord` handles and passes `byref` to C. Callers hold `InputRecordPy`, not handles.

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) — §2 binding C structs via the C API
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html)
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) — §7.2 scalar ctypes, libffi
- [Part V — ctypes Handle Pool Design Pattern](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) — §9 C++ handle pool, complex-type return via handles
- [ctypes — Structures and unions](https://docs.python.org/3/library/ctypes.html#structures-and-unions)
- [ctypes — Type conversions](https://docs.python.org/3/library/ctypes.html#type-conversions), [Pointers](https://docs.python.org/3/library/ctypes.html#pointers)
- [ctypes — `create_string_buffer`](https://docs.python.org/3/library/ctypes.html#ctypes.create_string_buffer), [`byref`](https://docs.python.org/3/library/ctypes.html#ctypes.byref)
- [CFFI — struct/array example](https://cffi.readthedocs.io/en/stable/overview.html#struct-array-example-minimal-in-line)
- [Handle (computing)](https://en.wikipedia.org/wiki/Handle_(computing)) — abstract reference to a resource managed by another system
- Demo: [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct)
