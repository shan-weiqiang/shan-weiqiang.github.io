---
layout: post
title:  "Undefined-Symbol Policies When Linking Executables and Shared Libraries"
date:   2026-08-23 10:00:00 +0800
tags: [cpp, systems]
---

GNU `ld` distinguishes undefined symbols by where the reference originates. A
reference originating from a regular object file used to construct the current
output is controlled independently from a reference already present in an
input shared library. This distinction applies even when the input shared
library is reached transitively through `DT_NEEDED`.

This article explains the effective GNU `ld` defaults when linking executables
and shared libraries, the option pair controlling each category, and the
special case in which a regular object file needs a symbol defined only by an
indirect shared-library dependency. It then applies those rules to pure virtual
interfaces and provider-owned C++ objects.

* toc
{:toc}

## Effective defaults

| Output | Regular `.o` undefined symbols | Input/transitive `.so` undefined symbols | Effective policy |
| --- | ---: | ---: | --- |
| Executable | Rejected | Rejected | `--no-undefined` + `--no-allow-shlib-undefined` |
| Shared library | Allowed | Allowed | `-z undefs` + `--allow-shlib-undefined` |

These are effective policies; the compiler driver does not necessarily pass
those exact options explicitly.

## Policy for current-target object files

This policy applies only to unresolved references originating from regular
`.o` files used to construct the current output:

```text
--no-undefined / -z defs
    Reject unresolved references from regular .o inputs.

-z undefs
    Permit unresolved references from regular .o inputs.
```

| Output | Policy selection | Unresolved symbol from current target's `.o` files |
| --- | --- | ---: |
| Executable | **Default:** `--no-undefined` | Rejected |
| Executable | Non-default: `-z undefs` | Allowed by the static linker |
| Shared library | **Default:** `-z undefs` | Allowed and retained as `UND` |
| Shared library | Non-default: `--no-undefined` | Rejected |

`--no-undefined` does not control unresolved references already contained in
input shared libraries.

## Policy for depended shared libraries

This policy applies only to unresolved references originating from directly or
transitively depended `.so` files:

```text
--no-allow-shlib-undefined
    Reject unresolved references found in depended shared libraries.

--allow-shlib-undefined
    Permit unresolved references found in depended shared libraries.
```

| Output | Policy selection | Unresolved symbol from direct/transitive `.so` |
| --- | --- | ---: |
| Executable | **Default:** `--no-allow-shlib-undefined` | Rejected |
| Executable | Non-default: `--allow-shlib-undefined` | Allowed |
| Shared library | **Default:** `--allow-shlib-undefined` | Allowed |
| Shared library | Non-default: `--no-allow-shlib-undefined` | Rejected |

`--allow-shlib-undefined` does not control unresolved references originating
from regular `.o` inputs.

The origin of the reference selects the policy:

```text
Reference originates from target.o
    -> controlled by --no-undefined / -z undefs

Reference originates from an input or transitive .so
    -> controlled by --[no-]allow-shlib-undefined
```

## A symbol required by `.o` but defined only indirectly

Consider this dependency relationship:

```text
target.o
    -> requires function_b()

libA.so
    -> DT_NEEDED: libB.so
                         -> defines function_b()
```

The link command specifies only A:

```bash
g++ target.o -lA ...
```

Although B contains the required symbol, modern GNU `ld` does not normally use
transitive `DT_NEEDED` libraries as direct providers for references originating
from `target.o`. For an executable, the default link therefore fails. For a
shared-library output, the default link can succeed only because undefined
references from regular `.o` inputs are permitted; `function_b` remains `UND`
in the resulting shared library rather than being resolved by the static
linker.

| Output and policy | Symbol-resolution result | Resulting `DT_NEEDED` relationship |
| --- | --- | --- |
| Executable, default | Fails because B is not accepted as a direct provider | No output is produced |
| Executable with `--allow-shlib-undefined` | Still fails because the reference originates from `target.o`, not from a `.so` | No output is produced |
| Shared library, default | Succeeds, but `function_b` remains `UND` | B is not recorded directly; if A is retained, B remains reachable only through A's `DT_NEEDED` entry |
| Shared library with `--allow-shlib-undefined` | Same as the default: succeeds with `function_b` still `UND` | B is not recorded directly; if A is retained, B remains reachable only through A's `DT_NEEDED` entry |
| Shared library with `--no-undefined` | Fails because the reference from `target.o` remains unresolved | No output is produced |
| Either output with B explicitly linked using `-lB` | Succeeds and resolves the reference against a direct dependency | B can be recorded as a direct `DT_NEEDED` dependency |
| Either output with `--copy-dt-needed-entries` | Can recursively use B to resolve the reference | B can be copied into the output as a direct `DT_NEEDED` dependency |

With `--as-needed`, A may also be omitted if it does not directly satisfy any
required reference and has no other reason to be retained. In that case, the
output can retain `function_b` as `UND` without recording either A or B. Using
`--no-as-needed` can retain A, but explicitly linking `-lB` expresses the
actual direct dependency more accurately.

The normal solution is to declare B as a direct link dependency because
`target.o` directly consumes B's symbol:

```bash
g++ target.o -lA -lB ...
```

## Pure virtual interfaces and executable linking

A virtual call through a pure interface is not an ordinary direct symbol
reference:

```cpp
class Task
{
public:
    virtual ~Task() = default;
    virtual void run() = 0;
};

void execute(Task& task)
{
    task.run();
}
```

The compiler can generate `execute(Task&)` without knowing any derived class.
The generated code follows the virtual-call ABI:

```text
load the object's vptr
    -> load the run() address from its vtable slot
    -> call that address indirectly
```

Consequently, the caller's object file does not normally contain an undefined
reference to a concrete override such as `ConcreteTask::run()`. The caller
never names that symbol. It contains the complete dispatch instructions
instead.

An executable containing only this interface and call site can therefore link
successfully without linking a concrete provider:

```text
executable
    defines: execute(Task&)
    undefined: no ConcreteTask::run() reference
    DT_NEEDED: no provider required by this virtual call site
```

A concrete implementation becomes necessary when the program needs a real
object. It can be supplied by a normally linked library or obtained later:

```text
dlopen(provider)
    -> dlsym(factory)
    -> factory returns Task*
    -> object carries the provider's vtable
    -> execute(*task) reaches ConcreteTask::run() indirectly
```

> A pure virtual interface supplies a complete dispatch contract, not a
> concrete function body. A call through the interface does not create an
> undefined reference to a particular concrete override, so that override does
> not participate in normal executable linking unless other code names it
> directly.

This conclusion applies specifically to the override reached through virtual
dispatch. Other odr-used interface members can still require definitions:

```cpp
class Task
{
public:
    virtual ~Task();  // Requires a definition when odr-used.
    virtual void run() = 0;
    void stop();      // Requires a definition when called.
};
```

An explicit call to a base implementation, interface static data, an
out-of-line key function, or code constructing a named derived class can
likewise introduce ordinary symbol dependencies.

## Pure-virtual semantics and provider-owned instances

The `= 0` marker changes the class contract, not the ordinary virtual-call
instructions:

```cpp
class Task
{
public:
    virtual ~Task() = default;
    virtual void run() = 0;
};
```

It has two related effects:

1. `Task` is abstract and cannot be instantiated as a complete object.
2. A derived class cannot be instantiated until the inheritance hierarchy
   provides a final overrider for `run()`.

An immediate derived class does not have to implement `run()`; it may remain
abstract. The requirement applies when a class is instantiated:

```cpp
class IntermediateTask : public Task
{
    // Still abstract.
};

class ConcreteTask final : public IntermediateTask
{
public:
    void run() override {}
};

ConcreteTask task;  // Valid: run() now has a final overrider.
```

Purity and the existence of a function body are separate. A pure virtual
function may have an out-of-line definition and still remain pure:

```cpp
void Task::run()
{
    // Optional base behavior, callable explicitly as Task::run().
}
```

A derived class must still override it to become concrete. A pure virtual
destructor is the important special case: it makes the class abstract but
still requires a definition because derived destruction invokes it.

### Abstract classes and vtables

Although an abstract class cannot exist as a complete object, its base
subobject exists inside derived objects. Under common GCC/Clang ABIs, the
abstract class can therefore have vtable and RTTI data. Conceptually:

```text
Task vtable
    run  -> pure slot
    stop -> Task::stop(), if stop() is non-pure
```

Under the Itanium C++ ABI, a pure slot may contain `__cxa_pure_virtual`, a
wrapper around it, or a null pointer. It is not a usable implementation.

A concrete derived class has a corresponding table whose pure slot is
replaced:

```text
ConcreteTask vtable
    run  -> ConcreteTask::run()
    stop -> Task::stop()
```

The compiler and linker form class vtables as shared static data. Construction
does not normally populate every function entry separately for each object.
Instead, construction associates the object with the appropriate table by
initializing its vptr:

```text
construct Task base subobject
    -> vptr refers to Task's construction-stage table

construct ConcreteTask portion
    -> vptr refers to ConcreteTask's table
```

### The client/provider boundary

A client-side virtual call contains a complete dispatch implementation:

```cpp
void execute(Task& task)
{
    task.run();
}
```

It does not contain the concrete behavior. The object supplied at runtime
provides the vptr whose vtable slot selects that behavior:

```text
client machine code             provider-created runtime object
-------------------             -------------------------------
load vptr                 +     vptr -> ConcreteTask vtable
load run slot                         run -> ConcreteTask::run()
indirect call
```

The concrete function is compiled earlier on the provider side; runtime does
not generate it. Runtime construction associates an object with its
class-specific table, and invocation selects the address through that table.

To preserve implementation isolation, the provider should own construction:

```cpp
// Public contract
class Task
{
public:
    virtual ~Task() = default;
    virtual void run() = 0;
};

extern "C" Task* create_task();
extern "C" void destroy_task(Task* task);
```

The provider alone knows and constructs the concrete type:

```cpp
class ConcreteTask final : public Task
{
public:
    void run() override;
};

extern "C" Task* create_task()
{
    return new ConcreteTask;
}

extern "C" void destroy_task(Task* task)
{
    delete task;
}
```

The client obtains only the abstract pointer:

```cpp
Task* task = create_task();
task->run();
destroy_task(task);
```

Provider-side construction is not required by the C++ language. A client that
knows `ConcreteTask` may construct it directly. It is an architectural
requirement when the goal is to keep the concrete type, layout, constructor,
and override symbols outside the client.

Creation and destruction must be designed together. A virtual destructor
allows polymorphic deletion, but a strict binary boundary may prefer paired
provider-owned create/destroy functions so allocation and deallocation occur
in the same module.

With ordinary shared linking, the client may have an undefined reference and
`DT_NEEDED` entry for the factory library, while still having no direct
reference to `ConcreteTask::run()`. With explicit loading, `dlopen()` and
`dlsym()` can remove even the factory from the executable's normal link and
startup dependency graph.

The resulting isolation is:

```text
provider-owned concrete type
    -> provider constructs object
    -> object carries provider vtable
    -> client receives Task*
    -> client performs fixed indirect dispatch
    -> provider-owned override executes
```

The central conclusion is:

> The pure virtual marker enforces an abstract contract, while virtual dispatch
> lets client code compile without a symbolic dependency on a concrete
> implementation. To preserve that separation in an SDK, the provider creates
> the concrete object and exposes only the interface and a safe lifetime
> contract to the client.

## Why a pure virtual destructor still requires a definition

A pure virtual destructor combines two independent properties:

```cpp
class Task
{
public:
    virtual ~Task() = 0;
};

Task::~Task() = default;
```

- `virtual` permits destruction through a base pointer to begin with the
  most-derived destructor.
- `= 0` makes `Task` abstract.
- The definition supplies the code required to destroy the `Task` base
  subobject.

Providing the definition does not remove purity. `Task` remains abstract and
cannot be instantiated as a complete object.

Every derived object contains its base-class subobject. Its destruction must
therefore execute the complete destructor chain:

```text
ConcreteTask::~ConcreteTask()
    -> destroy ConcreteTask members
    -> Task::~Task()
    -> destroy Task members
```

The derived destructor's call to the base destructor is mandatory. It is not
an optional virtual operation selected only when user code calls it. Even an
empty base destructor needs a callable definition so the generated destruction
chain has a valid target.

Without that definition:

```cpp
class Task
{
public:
    virtual ~Task() = 0;  // Declaration only: no Task::~Task() definition.
};

class ConcreteTask final : public Task
{
public:
    ~ConcreteTask() override = default;
};

int main()
{
    ConcreteTask task;
}
```

compilation may succeed, but linking normally fails with an error such as:

```text
undefined reference to Task::~Task()
```

A virtual destructor also supports deletion through the interface:

```cpp
Task* task = create_task();
delete task;
```

Conceptually, two mechanisms participate:

```text
delete Task*
    -> virtual dispatch selects ConcreteTask::~ConcreteTask()
    -> normal destructor chaining invokes Task::~Task()
```

A strict SDK boundary may still prefer a provider-owned
`destroy_task(Task*)` function so allocation and deallocation remain in the
same binary module.

This differs from an ordinary pure virtual operation:

```cpp
virtual void run() = 0;
```

If every concrete derived class overrides `run()`, normal virtual dispatch
never needs a body for `Task::run()`. Destruction is structurally different:
the language always destroys every base subobject after destroying the derived
portion.

The essential rule is:

> A pure virtual destructor makes the class abstract, but every derived-object
> destruction must still invoke the base destructor. Therefore the pure base
> destructor must have a definition.
