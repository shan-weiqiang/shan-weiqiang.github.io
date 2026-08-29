---
layout: post
title:  "Polymorphism, Type Erasure, and std::function"
date:   2026-08-23 11:00:00 +0800
tags: [cpp, data-typing]
---

Polymorphism means that the same operation or interface can be applied to
values of different types, with behavior appropriate to each type. It needs a
common interface, multiple type-specific implementations, and a selection
mechanism.

A useful C++ classification is:

- **Static polymorphism:** selection happens during compilation.
- **Runtime polymorphism:** selection uses runtime state.

Static polymorphism can generate type-specific adapters that are later stored
and dispatched through a runtime interface.

![Static and runtime polymorphism, type erasure, function tables, virtual dispatch, and std::function](/assets/images/polymorphism_type_erasure_std_function.png)

Here, virtual dispatch is classified operationally as type erasure: callers
use a base interface that hides the concrete dynamic type, while the compiler's
vtable is the function table that preserves type-specific operations.

* toc
{:toc}

## Static polymorphism

Static polymorphism selects an implementation before execution, so runtime
dispatch is unnecessary.

### Function overloading

```cpp
void process(Image&);
void process(Command&);

process(image);    // Selects process(Image&).
process(command);  // Selects process(Command&).
```

The compiler resolves the call using static argument types, conversions,
constraints, and overload-ranking rules.

### Templates and specialization

```cpp
template <typename T>
void process(T& value)
{
    value.execute();
}
```

The compiler instantiates distinct typed functions such as `process<Image>`
and `process<Command>`. The concrete type remains known in each instantiation.
Templates generate typed code; they do not by themselves erase a type.
Parameterization can also produce different layouts, such as `Buffer<64>` and
`Buffer<128>`, without creating a runtime-polymorphic interface.

## Runtime polymorphism

Runtime polymorphism applies when the implementation cannot be fixed solely
from the call site's static types.

### Closed tagged dispatch without type erasure

```cpp
using Message = std::variant<Image, Command>;

std::visit(
    [](auto& value) {
        value.execute();
    },
    message);
```

The active alternative is selected at runtime, but `Image` and `Command`
remain visible in `std::variant<Image, Command>`. Under the conventional
definition, their types have not been erased. Type erasure is therefore not
required for every form of runtime polymorphism.

See [Closed Tagged Dispatch — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
for the detailed storage, index, visitation, and lifetime model.

### Type erasure

Type erasure converts a concrete typed object into a uniform runtime
representation that no longer exposes the concrete type to its consumer. It
usually preserves selected behavior through function pointers or an operation
table.

#### Virtual interfaces

A virtual interface hides the concrete dynamic type behind a base-class
interface. Concrete implementations participate in the hierarchy and override
the same virtual operation:

```cpp
class Operation
{
public:
    virtual ~Operation() = default;
    virtual void execute() = 0;
};

class ImageOperation final : public Operation
{
public:
    void execute() override
    {
        processImage();
    }
};

class CommandOperation final : public Operation
{
public:
    void execute() override
    {
        processCommand();
    }
};

void run(Operation& operation)
{
    operation.execute();
}
```

The caller of `run()` knows only `Operation`. At runtime, the object's vptr
selects the appropriate entry in a compiler-generated vtable. Operationally,
that vtable is a function table whose compatible slots point to type-specific
implementations. The compiler and language object model generate and manage
the table, object adjustment, and indirect call.

#### Function tables

The same erased runtime interface can be represented explicitly as object
storage plus function-table slots with uniform signatures:

```cpp
struct ErasedOperation
{
    void* object;
    void (*execute)(void*);
};

template <typename T>
ErasedOperation erase(T& object)
{
    return {
        &object,
        [](void* pointer) {
            static_cast<T*>(pointer)->execute();
        }};
}

void run(const ErasedOperation& operation)
{
    operation.execute(operation.object);
}
```

`erase<T>()` runs while `T` is known to the compiler. It generates a
type-specific adapter that performs the correct cast and call, but every
generated adapter has the same erased signature, `void(void*)`. Consequently,
the `execute` slot can store the adapter for any supported concrete type.

```text
Concrete type T
    -> compile-time template instantiation
    -> type-specific adapter with the signature void(void*)
    -> function-table slot stores that adapter
    -> runtime dispatch invokes the stored function pointer
```

Two moments must be distinguished:

- **Binding or registration:** generate or select the adapter and store its
  function pointer.
- **Dispatch:** invoke the already-stored function pointer at runtime.

Runtime invocation does not perform overload resolution among candidates.
Construction has already selected the adapter. Type erasure is therefore one
important runtime-polymorphism technique, but not a synonym for all
polymorphism.

## Static implementations feeding runtime polymorphism

Static polymorphism can generate a family of type-specific implementations
that later become dispatch candidates for a type-erased runtime interface.
Here, “candidates” means functions available for binding into an erased slot.
Construction or registration selects one candidate and stores its address;
runtime invocation follows that address without performing overload
resolution.

### Virtual interfaces

With a virtual interface, the user writes a derived class and supplies each
override explicitly. The implementations can be completely different:

```cpp
class ImageOperation final : public Operation
{
public:
    void execute() override
    {
        processImageWithGpu();
    }
};

class CommandOperation final : public Operation
{
public:
    void execute() override
    {
        validateCommand();
        sendCommand();
    }
};
```

The compiler generates the class-specific vtables and any required dispatch
thunks. Each object points to the table for its dynamic type, and a virtual
call selects the corresponding function-table entry at runtime. The common
virtual signature makes dispatch possible, while the user remains free to
write unrelated implementation bodies for different derived classes.

### Explicit function tables

Without templates, users can populate an erased function-table slot with
separately written functions:

```cpp
void executeImage(void* object);
void executeCommand(void* object);

ErasedOperation image{&image_object, &executeImage};
ErasedOperation command{&command_object, &executeCommand};
```

The functions have the same erased signature, but their names and
implementations can be completely independent. Runtime dispatch invokes
whichever pointer was stored during binding.

Static polymorphism can remove this repetitive adapter work:

```cpp
template <typename T>
void executeAdapter(void* object)
{
    static_cast<T*>(object)->execute();
}
```

Template instantiation generates functions such as:

```cpp
executeAdapter<ImageOperation>(void*);
executeAdapter<CommandOperation>(void*);
```

They have the same erased signature and can therefore occupy the same
function-table slot. This is the bridge between the two stages:

```text
Compile time:
    instantiate type-specific functions with a uniform erased signature

Binding time:
    store one generated function pointer in an erased operation table

Runtime:
    dispatch through the stored function pointer
```

The ordinary template form imposes one structural implementation pattern on
all instantiations: cast the erased object to `T` and perform the same generic
operation. This is less freely customized than independently written virtual
overrides or hand-written erased functions.

That restriction is not absolute. Function overloads, template
specializations, policy types, concepts, and `if constexpr` can provide
type-specific behavior when required. Increasing customization, however, also
reduces the simplicity gained from one uniform adapter template.

`std::function` is the representative hybrid. Its templated constructor
generates callable-specific invocation and lifetime adapters during
compilation. The `std::function` object then erases the callable type, stores
the selected adapters, and dispatches through them at runtime.

## `std::function` as a hybrid case study

`std::function` combines static polymorphism, type erasure, and runtime
polymorphism.

### First template level: public signature

The outer specialization fixes the stable callable interface:

```cpp
std::function<int(std::string)>
```

It is one specialization of `std::function<R(Args...)>` and fixes
`operator()`'s signature.

### Second template level: concrete callable

The instantiated class has a templated constructor accepting many callable
types:

```cpp
std::function<int(int)> function;

function = [](int value) { return value + 1; };
function = &freeFunction;
function = CallableObject{};
```

For each concrete callable type, the constructor can instantiate an adapter:

```cpp
template <typename Callable>
int invoke(void* storage, int argument)
{
    return std::invoke(
        *static_cast<Callable*>(storage),
        argument);
}
```

Implementations also need type-specific destruction, copy, move, and storage
operations. The standard does not mandate an operation-table implementation,
but it is a useful conceptual model.

```text
Compile time:
    instantiate the constructor for Callable
    -> generate or select Callable-specific adapters

Construction:
    store the Callable and its corresponding adapters

Runtime:
    call std::function::operator()
    -> dispatch through the stored invocation adapter
```

It is more precise to say that templates generate adapters than runtime
“candidates.” Construction has already selected one adapter; runtime invocation
simply follows it.

Thus `std::function` combines:

1. **Static polymorphism** to generate type-specific adapters.
2. **Type erasure** to remove the callable type from the public value.
3. **Runtime polymorphism** to dispatch through the stored adapter.

See [Type Erasure II — std::function](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
for the focused implementation walkthrough.

## Two ways to isolate type-specific logic from a core library

Type-specific behavior can be kept outside a core library without requiring
one particular polymorphism technique. Two common designs perform the
isolation at different stages: compile-time customization through public
templates and runtime registration through a type-erased interface.

Both designs pursue the same architectural result:

> The core library operates through a stable, type-independent boundary and
> does not need to be rebuilt for every application data type.

### Compile-time isolation through templates

A library can expose a templated header API and let client code supply the
concrete type during compilation:

```cpp
template <typename T>
void store(const T& value)
{
    ByteBuffer bytes = Serializer<T>::serialize(value);
    writeBuffer(bytes.data(), bytes.size());
}
```

When the client calls:

```cpp
archive.store<CustomerRecord>(record);
```

the client translation unit instantiates `store<CustomerRecord>()` and
`Serializer<CustomerRecord>`. The compiled core library implements only the
type-independent byte operation:

```text
Client compilation:
    CustomerRecord
        -> instantiate Serializer<CustomerRecord>
        -> serialize to bytes

Core-library boundary:
    writeBuffer(data, size)
        -> store bytes without knowing CustomerRecord
```

The concrete type remains visible throughout the typed client operation.
Consequently, this approach is static polymorphism or compile-time
customization, not C++ type erasure. Serialization removes the typed object
from the later storage boundary, but the template API itself does not erase
its C++ type.

The type-specific template definition may live in a public SDK header while
its instantiation is emitted into the client executable or client shared
library. Merely parsing the template while compiling the core does not
instantiate it for a concrete data type.

### Runtime isolation through type support

A core library can instead define a type-erased runtime interface:

```cpp
class SerializationSupport
{
public:
    virtual ~SerializationSupport() = default;

    virtual bool serialize(
        const void* object,
        SerializedPayload& payload) const = 0;

    virtual bool deserialize(
        const SerializedPayload& payload,
        void* object) const = 0;
};
```

A client or integration layer provides a concrete implementation and registers
it during runtime setup:

```cpp
registry.registerType(
    "example.CustomerRecord",
    std::make_shared<CustomerRecordSerializationSupport>());
```

The core retains the registered interface and invokes it later through virtual
dispatch:

```text
Runtime registration:
    CustomerRecordSerializationSupport
        -> register under a type identity
        -> bind to a generic archive

Per operation:
    generic core
        -> SerializationSupport::serialize(void*, payload)
        -> virtual dispatch
        -> CustomerRecord-specific implementation
```

Here the core cannot see the concrete C++ object type behind `void*`. The
virtual object preserves the operations needed to manipulate that hidden type.
This is runtime polymorphism implemented with type erasure.

The implementation must already exist before it can be registered. Runtime
binding does not mean runtime code generation: the type-support class and its
serialization logic may have been handwritten, generated from a schema, or
built as an adapter over generated callbacks.

### Same isolation goal, different binding stage

| Aspect | Compile-time template customization | Runtime type support |
| --- | --- | --- |
| Normal call direction | Client calls core | Core calls registered implementation |
| Binding time | Client compilation | Runtime registration |
| Client supplies type knowledge | During client compilation | During runtime registration |
| External implementation mandatory | Depends on whether the template provides a default | Yes |
| Can bypass abstraction | Usually yes, by calling the raw core API | No within the registered interface |
| Core-facing boundary | Serialized bytes | Opaque object and virtual interface |
| Selection mechanism | Template instantiation and direct calls | Virtual or function-table dispatch |
| Type erasure | Not inherently | Yes |
| Inversion of control | Not inherently | Fundamental |
| Core knows concrete data types | No | No |
| Core rebuilt for new types | No | No |
| Type-specific implementation supplied with the client deployment | Yes | Yes |

In both designs, the client-side program or deployment must contain the
executable type-specific implementation. This does not mean that application
developers must author it themselves: it may come from a library template,
generated code, a separately compiled support library, or a plugin.

## Construction is the concrete-type dependency boundary

Runtime polymorphism hides a concrete type at the dispatch site, but a concrete
instance must first be created somewhere. That construction site is where the
type erasure begins:

```text
construction site
    -> knows ConcreteOperation and its construction requirements
    -> creates the concrete object
    -> converts it to Operation*, an erased wrapper, or a function table
    -> type-independent code performs runtime dispatch
```

Code that directly constructs a derived object must see its declaration and
usually its complete definition. Its object file can also acquire ordinary
symbol dependencies on the concrete constructor, destructor, vtable, and any
public construction dependencies:

```cpp
#include "image_operation.hpp"

std::unique_ptr<Operation> createOperation()
{
    return std::make_unique<ImageOperation>();
}
```

The consumer of the resulting `Operation*` does not need to know
`ImageOperation`, but the translation unit containing `createOperation()` does.
If this construction code is placed in a normally linked provider library, the
host can remain source-isolated from the concrete type while still recording a
normal binary dependency on that provider:

```text
host
    -> DT_NEEDED: libimage_operation.so
        -> concrete type, constructor, vtable, and private dependencies
```

The concrete type's source dependencies remain owned by the provider; they do
not all become headers of every library that links to it. The provider and its
own `DT_NEEDED` closure do, however, remain part of the host's normal startup
dependency graph.

### Moving construction behind `dlopen()`

A plugin boundary can remove the concrete provider from the host's ordinary
link step and `DT_NEEDED` graph. The host compiles only against a stable
interface and registry contract, then loads providers selected at runtime:

```text
host build
    -> knows Operation and Registry
    -> no reference to ImageOperation
    -> no DT_NEEDED entry for libimage_operation.so

runtime
    -> dlopen("libimage_operation.so")
    -> provider registers an ImageOperation factory
    -> registry creates Operation objects
    -> host dispatches through Operation
```

The provider owns the concrete construction code:

```cpp
class ImageOperation final : public Operation
{
public:
    void execute() override;
};

extern "C" bool register_plugin(Registry* registry)
{
    registry->add(
        "image",
        []() -> std::unique_ptr<Operation> {
            return std::make_unique<ImageOperation>();
        });
    return true;
}
```

The host resolves and invokes only the stable registration entry point:

```cpp
using RegisterPlugin = bool (*)(Registry*);
using LibraryHandle = std::unique_ptr<void, int (*)(void*)>;

LibraryHandle library{
    dlopen(path, RTLD_NOW | RTLD_LOCAL),
    &dlclose};
if (!library) {
    throw PluginError(dlerror());
}

auto register_plugin = reinterpret_cast<RegisterPlugin>(
    dlsym(library.get(), "register_plugin"));
if (register_plugin == nullptr || !register_plugin(&registry)) {
    throw PluginError("plugin registration failed");
}
```

The host must retain `library` for as long as the registry can call a factory
or any object created by that factory remains alive. Unloading it earlier
invalidates the provider's functions, vtables, and runtime metadata.

A provider can also register through a shared-library constructor or static
registration object that runs during `dlopen()`. That makes registration
automatic, but it introduces initialization-order, error-reporting, symbol
visibility, and unloading-lifetime concerns. An explicit versioned
`register_plugin` entry point is usually easier to validate and control.

`dlopen()` therefore changes when the dependency becomes mandatory:

| Boundary | Concrete provider dependency |
| --- | --- |
| Direct construction in the host | Compile and link time |
| Normally linked provider factory | Link time and process startup |
| `dlopen()` plus runtime registration | Only when the host chooses to load and use the provider |

The provider has not disappeared: its binary and its own dependencies must
still be present when the feature is loaded. What disappears is the host's
compile-time knowledge of the concrete type, its direct link dependency on the
provider, and its requirement to load that provider before `main()`.
