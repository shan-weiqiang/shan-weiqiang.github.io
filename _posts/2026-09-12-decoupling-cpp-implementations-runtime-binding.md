---
layout: post
title:  "Decoupling C++ Implementations with Interfaces and Runtime Binding"
date:   2026-09-12 09:00:00 +0800
tags: [cpp, type-erasure, runtime-binding, linking, pimpl]
---

To let a client invoke an implementation without directly referencing that
implementation's symbols, use three steps:

1. Define a common interface.
2. Represent the implementation through a callable value.
3. Bind that value to a concrete implementation at runtime.

![Decoupling an implementation requires a common interface, a callable value, and runtime binding](/assets/images/cpp_interface_callable_runtime_binding.png)

The dependency does not disappear. It moves from a concrete symbol referenced
at link time to an implementation selected and supplied at runtime.

* toc
{:toc}

## Start with a direct dependency

Suppose a client calls `process()` directly:

```cpp
struct Data {
    int value;
};

void process(Data& data);

void client(Data& data)
{
    process(data);
}
```

The object file containing `client()` refers to the symbol for `process()`.
Moving the definition of `process()` to another source file hides its body, but
the program must still provide that symbol when it is linked or loaded.

To remove this direct reference, the client must call an operation supplied as
a value instead of naming `process()`.

## Step 1: define a common interface

First, define the operation without naming an implementation:

```cpp
struct Data {
    int value;
};

using ProcessFunction = void (*)(Data& data);
```

Every implementation will be invoked through this signature.

## Step 2: represent the implementation as a callable value

Pass the operation as a function-pointer value:

```cpp
void client(const ProcessFunction process, Data& data)
{
    process(data);
}
```

`client()` now refers only to the `ProcessFunction` signature. It does not
refer to a concrete implementation function.

## Step 3: bind a concrete implementation at runtime

Define a concrete implementation:

```cpp
void multiply_by_three(Data& data)
{
    data.value *= 3;
}

void host()
{
    const ProcessFunction process = &multiply_by_three;

    Data data{7};
    client(process, data);  // data.value is now 21.
}
```

The host refers to `multiply_by_three`; `client()` does not. Assigning its
address to `process` creates the runtime binding, and calling `process(data)`
dispatches through it.

Virtual methods use the same underlying idea on common C++ ABIs. A base-class
pointer provides the common interface, the object carries a pointer to a table
of virtual functions, and a virtual call selects a function address from that
table. The compiler generates this binding and dispatch machinery. C++
specifies virtual-call behavior but does not require a particular vtable
representation.

## Selecting an implementation from a loaded library

The preceding example selects `multiply_by_three` in ordinary host code. A
host can instead select an implementation from a shared library at runtime.

With `dlopen()` and `dlsym()`, the host actively looks up the provider using
strings:

```cpp
using GetProcessFunction = ProcessFunction (*)();

void* library = dlopen("libmultiplier.so", RTLD_NOW | RTLD_LOCAL);
void* symbol = dlsym(library, "get_process_function");
```

The plugin exports the known lookup entry point:

```cpp
extern "C" ProcessFunction get_process_function();
```

The example omits error handling, conversion of the `dlsym()` result, and RAII
management of the library handle. Those details are required in production.
The library must remain loaded while the returned function pointer may be
called.

A registry reverses the lookup direction. Libraries register their function
pointers when they are loaded, and the host later asks the registry for one:

```text
load library -> register function -> look up function -> call implementation
```

The host no longer has an ordinary link-time reference to the selected function.
It depends instead on the loader or registry contract, and the concrete
provider is resolved at runtime.

## Why PImpl is different

PImpl hides a concrete implementation definition behind an opaque pointer:

```cpp
#include <memory>

class Widget {
public:
    Widget();
    ~Widget();

    void run();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
```

The client does not need the definition of `Widget::Impl`, so changes to its
private representation need not cause client recompilation.

The client still refers to the public symbols:

```text
Widget::Widget()
Widget::run()
Widget::~Widget()
```

The library defining those symbols must therefore still be linked and loaded.
PImpl hides representation; it does not by itself replace direct calls with a
runtime-supplied callable value.
