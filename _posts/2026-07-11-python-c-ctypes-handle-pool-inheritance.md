---
layout: post
title:  "Python/C IX — Inheritance Handle Pool"
date:   2026-07-11 10:00:00 +0800
tags: [python]
---

* toc
{:toc}

This article is Part IX of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) covers hand-written extensions and `PyCapsule` opaque handles. [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) covers bytecode vs C method dispatch. [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) covers loading plain C libraries through `_ctypes` and libffi. [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) covers struct mirroring, keepalive, and the generalized handle idea behind `ctypes.Structure`. [Part V — Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) introduces the layered handle-pool pattern for C++ behind a C ABI. [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) applies the capsule pattern to ROS 2 `rosidl` Python bindings and `rclpy`. [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) covers compile-time C++ bindings as an alternative to the handle-pool pattern. [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html) places the handle-pool design in the binding column of the series map.

Part IX extends Part V to **C++ inheritance**: a single pool wrapper type stores any `Animal` subclass, the bridge downcasts to `Dog*` or `Cat*` inside the library, and Python wrapper classes mirror the C++ hierarchy exactly — including which methods live on the base class and which on derived types.

Runnable demo: [c_ext_handle_inheritance](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance) in the [python](https://github.com/shan-weiqiang/python) repository.

```bash
make -C c_ext_handle_inheritance
python3 c_ext_handle_inheritance/test_handle_inheritance.py
```

| Section | Demo folder |
|---|---|
| §13.2–13.8 | [c_ext_handle_inheritance](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance) — [`cpp/`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance/cpp), [`python/`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance/python), [`test_handle_inheritance.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/test_handle_inheritance.py) |
| Part V contrast | [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding) (flat `TypeId`-per-class pool) |

---

## Section 13: ctypes Handle Pool for C++ Inheritance

### 13.1 Inheritance vs Part V Flat Types

Part V stored each C++ business class as its own `HandleObject` subclass. `HandlePool::get_as<Config>(handle, TypeId::Config)` used a per-type `TypeId` enum and `static_cast` after the check. That works when types are **unrelated** — `Config` and `Counter` share no base class.

Part IX targets a **C++ inheritance hierarchy**:

```
Animal (abstract)
├── Dog
└── Cat
```

The pool still stores `HandleObject` instances, but there is only **one pool wrapper type** — `AnimalObject` — regardless of whether the wrapped pointer is a `Dog*` or `Cat*`. Heterogeneity lives inside the `Animal*` the wrapper holds, not in separate pool entry types.

| | Part V ([`c_ext_handle_binding`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding)) | Part IX ([`c_ext_handle_inheritance`](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance)) |
|---|---|---|
| C++ model | unrelated classes | base + derived hierarchy |
| Pool `HandleObject` types | one per business class (`Config`, `Counter`, …) | one wrapper (`AnimalObject`) |
| `TypeId` values | `Config = 1`, `Counter = 2`, … | single `Animal = 1` |
| Bridge downcast | `static_cast` after `TypeId` check | `dynamic_cast` from `Animal*` |
| Python type selection | `handle_type` only | `handle_type` + `animal_get_kind` |
| Python class layout | one class per pool type | mirrors C++ inheritance tree |

The three-layer architecture from Part V (C++ → `extern "C"` bridge → ctypes Python) is unchanged. Part IX adds **runtime kind dispatch** on top of the existing handle-pool machinery.

---

### 13.2 Python Classes Mirror C++ Inheritance

**Rule:** every C++ class in the hierarchy — base or derived — has a corresponding Python class. Inheritance and method placement match the C++ side exactly.

**C++ layer** — [`animal.h`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/cpp/animal.h), [`dog.h`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/cpp/dog.h), [`cat.h`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/cpp/cat.h):

```cpp
class Animal {
public:
    virtual ~Animal() = default;
    virtual std::string name() const = 0;
    virtual AnimalKind get_kind() const = 0;
    virtual int age() const = 0;
    virtual Sex sex() const = 0;
    virtual Animal* friend_animal() const = 0;
};

class Dog : public Animal {
public:
    Animal* friend_animal() const override;
    Cat* friend_cat() const;
    bool is_friend(const Cat* cat) const;
    Cat* older_cat(Cat* one, Cat* two) const;
    // ...
};

class Cat : public Animal {
public:
    Animal* friend_animal() const override;
    Dog* friend_dog() const;
    bool is_friend(const Dog* dog) const;
    // ...
};
```

**Python layer** — [`animal.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/python/animal.py), [`dog.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/python/dog.py), [`cat.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/python/cat.py):

```python
class Animal(HandleResource):
    def name(self) -> str: ...
    def kind(self) -> AnimalKind: ...
    def age(self) -> int: ...
    def sex(self) -> Sex: ...
    def friend(self) -> Animal | None: ...

class Dog(Animal):
    @classmethod
    def create(...) -> "Dog": ...
    def friend_cat(self) -> "Cat | None": ...
    def is_friend(self, cat: "Cat | None") -> bool: ...
    def older_cat_ptr(self, one: "Cat", two: "Cat") -> "Cat | None": ...

class Cat(Animal):
    @classmethod
    def create(...) -> "Cat": ...
    def friend_dog(self) -> "Dog | None": ...
    def is_friend(self, dog: "Dog | None") -> bool: ...
```

Methods that exist on the C++ base (`name`, `age`, `friend_animal` → `friend()`) live on `Animal`. Methods that exist only on a derived type (`friend_cat`, `older_cat`) live on `Dog` or `Cat`. Factory methods (`Dog.create`, `Cat.create`) call the C create API and pass the returned handle through `wrap_handle`, so callers always receive the correct Python subclass.

![C++ and Python inheritance mirroring](/assets/images/python_c_ext_handle_pool_inheritance_uml.png)

---

### 13.3 Single Pool Wrapper: AnimalObject and get_kind

The handle pool manages **base-class objects only**. Every stored animal — whether the underlying pointer is a `Dog*` or `Cat*` — is wrapped in `AnimalObject`, which implements `HandleObject`:

```cpp
class AnimalObject : public HandleObject {
public:
    explicit AnimalObject(std::unique_ptr<Animal> animal);  // owned
    explicit AnimalObject(Animal* view);                    // borrowed view

    int type() const override;   // always TypeId::Animal
    bool owns() const;
    Animal* animal();
private:
    std::unique_ptr<Animal> owned_;
    Animal* view_;
};
```

There is only one pool `TypeId`:

```cpp
enum class TypeId : int {
    Animal = 1,
};
```

Because all pool entries share the same `TypeId`, Python cannot distinguish `Dog` from `Cat` using `handle_type` alone. The bridge exposes a second query — **`animal_get_kind`** — that calls the virtual `Animal::get_kind()` method:

```cpp
enum class AnimalKind : int {
    Animal = 0,
    Dog = 1,
    Cat = 2,
};

int animal_get_kind(int64_t handle) {
    Animal* animal = require_animal(handle);
    return static_cast<int>(animal->get_kind());
}
```

**Two-level type identification:**

| Query | Returns | Answers |
|---|---|---|
| `handle_type(handle)` | `TypeId::Animal` (or `-1`) | What kind of **pool entry** is this? |
| `animal_get_kind(handle)` | `AnimalKind::{Animal,Dog,Cat}` | What kind of **C++ object** does the entry wrap? |

The pool itself is homogeneous (`AnimalObject` only). Polymorphism is carried by the `Animal*` inside each wrapper and surfaced to Python through `get_kind`.

---

### 13.4 HandleResource: Owned vs Borrowed

Part V introduced `HandleResource` with a single ownership model — every wrapper owns its pool entry. Part IX adds a second mode because C++ objects can be **owned by another object** (e.g. a `Dog` owns its `Cat` friend via `std::unique_ptr<Cat>`) while Python still needs a handle to query the friend.

| Mode | C++ (`AnimalObject`) | Python (`HandleResource`) | `close()` behavior |
|---|---|---|---|
| **Owned** | `unique_ptr<Animal> owned_` | `owned=True` (default) | calls `handle_release` → destroys C++ object |
| **Borrowed** | raw `Animal* view_` | `owned=False` | drops Python reference only; pool entry kept |

```python
class HandleResource:
    def __init__(self, handle: int, *, owned: bool = True) -> None:
        self._handle = handle
        self._owned = owned

    def close(self) -> None:
        if self._closed or self._handle == 0:
            return
        if self._owned:
            _lib.handle_release(self._handle)
        self._handle = 0
        self._closed = True
```

**Creation path:** `dog_create` builds a `Dog` that owns its `Cat` friend via `std::unique_ptr<Cat>`. The bridge stores one **owned** `AnimalObject` wrapping `unique_ptr<Animal>` (the `Dog`). The embedded `Cat` is not a separate pool entry.

**Access path:** when Python calls `dog.friend()` or `dog.friend_cat()`, the bridge reads `dog->friend_cat()` — a raw `Cat*` into memory owned by the `Dog`. It stores a second **view** `AnimalObject` that holds only that pointer (`view_`), with no `unique_ptr`. The `Cat` object remains owned by the `Dog`'s `unique_ptr<Cat>`.

```cpp
HandleId ensure_view_handle(const Animal* animal) {
    const HandleId existing = lookup_animal_handle(animal);
    if (existing != kInvalidHandle) {
        return existing;
    }
    return store_view_animal(const_cast<Animal*>(animal));  // AnimalObject(Cat*) view
}
```

Python wraps the view handle with `owned=False`. Closing the borrowed wrapper does **not** call `handle_release`. When the owned primary is released, the bridge removes the view pool entry (which does not delete the `Cat`), then erases the owned entry. Destroying the owned `AnimalObject` runs its `unique_ptr<Animal>` destructor, which destroys the `Dog`; the `Dog` destructor in turn deletes its owned `Cat`.

![Owned and borrowed handle lifecycle](/assets/images/python_c_ext_handle_pool_owned_borrowed.png)

**Best practice:** create pool entries for embedded objects **on demand** from the Python side. If `friend()` is never called, no view handle enters the pool.

---

### 13.5 Returning Strings Across the C ABI

`std::string` cannot cross the ctypes boundary directly — ctypes knows C types (`char*`, fixed buffers), not C++ STL containers. The bridge copies into a caller-provided buffer; Python allocates the buffer and decodes the result into a native `str`.

**C bridge** — [`bridge.cpp`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/cpp/bridge.cpp):

```cpp
int copy_string(const std::string& value, char* out, int out_size) {
    if (out == nullptr || out_size <= 0) {
        set_error("output buffer must not be null");
        return -1;
    }
    std::snprintf(out, static_cast<size_t>(out_size), "%s", value.c_str());
    return 0;
}

int animal_get_name(int64_t handle, char* out, int out_size) {
    Animal* animal = require_animal(handle);
    if (animal == nullptr) {
        return -1;
    }
    return copy_string(animal->name(), out, out_size);
}
```

**Python** — [`_native.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_handle_inheritance/python/_native.py):

```python
NAME_MAX = 256

def _to_string(fn, handle: int) -> str:
    buf = ctypes.create_string_buffer(NAME_MAX)
    _check_status(fn(handle, buf, NAME_MAX))
    return buf.value.decode()
```

**Why this pattern:**

- C++ owns the `std::string` internally; only a **copy** crosses the ABI.
- Python allocates a fixed-size buffer (`NAME_MAX = 256`) on its stack — no dangling pointer.
- The decoded Python `str` is fully owned by Python after the call returns.
- `snprintf` truncates safely if the name exceeds `NAME_MAX - 1`.

The same out-buffer pattern applies to any C++ method that returns `std::string`, `std::vector`, or other heap-backed types that cannot be expressed as a plain C struct.

---

### 13.6 Bridge: Base Lookup, Then Derived Cast

Every typed C API function follows the same two-step pattern inside the bridge:

1. **Get the base wrapper** from the pool (`AnimalObject`).
2. **Cast to the derived type** with `dynamic_cast`.

```cpp
template <typename T>
T* get_animal_as(HandleId handle) {
    AnimalObject* wrapper = g_pool.get_as<AnimalObject>(handle);
    if (wrapper == nullptr) {
        set_error(/* ... */);
        return nullptr;
    }
    T* animal = dynamic_cast<T*>(wrapper->animal());
    if (animal == nullptr) {
        set_error("invalid handle or wrong type");
        return nullptr;
    }
    return animal;
}
```

**Example — dog-specific API:**

```cpp
int64_t dog_friend_cat_ptr(int64_t dog_handle) {
    Dog* dog = get_animal_as<Dog>(dog_handle);
    if (dog == nullptr) {
        return kInvalidHandle;
    }
    return ensure_view_handle(dog->friend_cat());
}

int dog_is_friend_cat_ptr(int64_t dog_handle, int64_t cat_handle) {
    Dog* dog = get_animal_as<Dog>(dog_handle);
    Cat* cat = get_animal_as<Cat>(cat_handle);
    if (dog == nullptr || cat == nullptr) {
        return -1;
    }
    return dog->is_friend(cat) ? 1 : 0;
}
```

**Contrast with Part V:** there, `get_as<Config>` used `static_cast` after a `TypeId` check because each pool entry type mapped 1:1 to a C++ class. Here, all entries are `AnimalObject`, so the bridge must recover the derived type from the stored `Animal*` pointer. `dynamic_cast` is safe **inside the C++ library** where RTTI is available. The C ABI itself still passes only `int64_t` handles — no C++ type information crosses the boundary.

Call chain for a typed operation:

```text
handle → AnimalObject → Animal* → dynamic_cast<Dog*> → Dog::friend_cat()
```

---

### 13.7 Python Dispatch: handle_type + get_kind → Correct Class

When any C API returns a handle, Python must construct the right wrapper class. **`wrap_handle`** performs a two-step dispatch so the real C++ type is always known on the Python side:

```python
def wrap_handle(handle: int, *, owned: bool = True) -> "Animal":
    from .animal import Animal
    from .cat import Cat
    from .dog import Dog
    from .types import AnimalKind, TypeId

    pool_type = _check_int(_lib.handle_type(handle))
    if pool_type != int(TypeId.ANIMAL):
        raise RuntimeError(f"unsupported pool type id: {pool_type}")

    kind = AnimalKind(_check_int(_lib.animal_get_kind(handle)))
    mapping: dict[AnimalKind, type[Animal]] = {
        AnimalKind.ANIMAL: Animal,
        AnimalKind.DOG: Dog,
        AnimalKind.CAT: Cat,
    }
    cls = mapping.get(kind, Animal)
    return cls(handle, owned=owned)
```

**Step 1 — pool type:** `handle_type(handle)` confirms the entry is an `AnimalObject` (`TypeId::Animal`). A wrong pool type raises immediately.

**Step 2 — runtime kind:** `animal_get_kind(handle)` calls the C++ virtual `get_kind()` and selects `Animal`, `Dog`, or `Cat` from the mapping.

Every handle-returning path funnels through `wrap_handle` or `wrap_optional_handle`:

| C API | Python entry point | Result type |
|---|---|---|
| `dog_create` | `Dog.create` → `wrap_handle` | `Dog` |
| `cat_create` | `Cat.create` → `wrap_handle` | `Cat` |
| `animal_friend_ptr` | `Animal.friend` → `wrap_optional_handle` | `Animal \| None` (re-dispatched to `Dog`/`Cat`) |
| `dog_friend_cat_ptr` | `Dog.friend_cat` → `wrap_optional_handle` | `Cat \| None` |
| `dog_older_cat_ptr` | `Dog.older_cat_ptr` → `wrap_optional_handle` | `Cat \| None` |

Callers never receive a bare `int` handle from the public Python API. `isinstance(dog, Dog)` and `dog.friend_cat()` type hints are accurate because dispatch happens at wrap time.

![wrap_handle two-step dispatch](/assets/images/python_c_ext_handle_pool_wrap_dispatch.png)

---

### 13.8 Comparison and When to Use

| | Part V flat pool | Part IX inheritance pool |
|---|---|---|
| C++ model | unrelated classes | base + derived hierarchy |
| Pool `HandleObject` types | one per business class | one wrapper (`AnimalObject`) |
| Python type selection | `handle_type` only | `handle_type` + `get_kind` |
| Downcast in bridge | `static_cast` + `TypeId` | `dynamic_cast` from `Animal*` |
| Python class tree | flat (one class per pool type) | mirrors C++ inheritance |
| Embedded object handles | N/A | lazy view handles on demand |

**Use Part IX when:**

- The C++ API is organized around a **polymorphic base class** with virtual methods.
- Derived types add type-specific operations (`Dog::older_cat`, `Cat::friend_dog`).
- You want Python `isinstance` / inheritance to match the C++ class tree.
- Objects can be **owned or borrowed** within the same hierarchy.

**Use Part V when:**

- C++ types are **unrelated** (no common base beyond `HandleObject`).
- Each type has a distinct pool entry and `TypeId`.
- No runtime downcast is needed in the bridge.

**When to prefer Part VII (pybind11) instead:** you can compile a dedicated extension module and want pybind11 to generate the inheritance bindings (`py::class_<Animal>, py::class_<Dog, Animal>`) without a handle pool or C ABI shim.

---

## References

- [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html)
- [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html)
- [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html)
- [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html)
- [Part V — Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) — flat `TypeId`-per-class pattern
- [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html)
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html)
- [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html)
- [ctypes — Python 3 documentation](https://docs.python.org/3/library/ctypes.html)
- [Handle (computing)](https://en.wikipedia.org/wiki/Handle_(computing))
- Demo: [c_ext_handle_inheritance](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_inheritance)
- Part V contrast: [c_ext_handle_binding](https://github.com/shan-weiqiang/python/tree/main/c_ext_handle_binding)
