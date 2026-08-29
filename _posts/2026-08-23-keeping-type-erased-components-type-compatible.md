---
layout: post
title:  "Keeping Type-Erased Components Type-Compatible"
date:   2026-08-23 09:00:00 +0800
tags: [cpp, type-erasure, rtti, abi]
---

Type erasure reduces template propagation, stabilizes interfaces, hides
implementation types, and allows code to operate on values whose concrete C++
types are unknown to the erased layer.

The loss of type information is also its central risk. Once related operations
have been converted to signatures such as `void*`, `std::shared_ptr<void>`, or
`std::function<void(void*)>`, the erased layer cannot prove that those
operations still agree about the original type.

* toc
{:toc}

## The problem

Consider an erased factory and callback registered independently:

```cpp
#include <functional>
#include <memory>

struct Image
{
    int width{};
};

struct Command
{
    int opcode{};
};

struct ErasedOperation
{
    std::function<std::shared_ptr<void>()> create;
    std::function<void(void*)> invoke;
};

ErasedOperation operation{
    []() -> std::shared_ptr<void> {
        return std::make_shared<Image>();
    },
    [](void* object) {
        // This compiles, but object actually points to Image.
        auto& command = *static_cast<Command*>(object);
        command.opcode = 7;
    }};

auto owner = operation.create();
operation.invoke(owner.get());  // Undefined behavior.
```

Each erased function is individually valid, but they do not cooperate
correctly. The factory produces `Image`, while the callback interprets the
object as `Command`. The erased signatures contain no information that lets
`ErasedOperation` detect the mismatch.

Possible results include:

- Memory corruption.
- Crashes far away from the invalid cast.
- Incorrect values that appear plausible.
- Failures that depend on optimization level or object layout.
- Plugin or ABI failures that occur only in deployment.

The essential rule is:

> Compatibility must be established before type erasure, or restored with
> reliable runtime type information before erased components are connected.

The following approaches solve this problem for different composition models.

## Create related erased operations through one typed interface

When all concrete types are known at registration time, generate every related
erased operation in one templated function. Users provide typed behavior; the
framework owns the casts.

```cpp
#include <functional>
#include <memory>
#include <type_traits>
#include <utility>

class ExecutionAdapter
{
public:
    std::shared_ptr<void> createInput() const
    {
        return m_create_input();
    }

    std::shared_ptr<void> createOutput() const
    {
        return m_create_output();
    }

    void invoke(void* input, void* output) const
    {
        m_invoke(input, output);
    }

private:
    using Create = std::function<std::shared_ptr<void>()>;
    using Invoke = std::function<void(void*, void*)>;

    ExecutionAdapter(Create create_input, Create create_output, Invoke invoke)
        : m_create_input(std::move(create_input)),
          m_create_output(std::move(create_output)),
          m_invoke(std::move(invoke))
    {
    }

    Create m_create_input;
    Create m_create_output;
    Invoke m_invoke;

    template <typename Input, typename Output, typename Callback>
    friend ExecutionAdapter makeExecutionAdapter(Callback&&);
};

template <typename Input, typename Output, typename Callback>
ExecutionAdapter makeExecutionAdapter(Callback&& callback)
{
    static_assert(
        std::is_invocable_r_v<void, Callback&, Input&, Output&>,
        "callback must accept Input& and Output&");

    std::function<void(Input&, Output&)> typed_callback(
        std::forward<Callback>(callback));

    return ExecutionAdapter(
        []() -> std::shared_ptr<void> {
            return std::make_shared<Input>();
        },
        []() -> std::shared_ptr<void> {
            return std::make_shared<Output>();
        },
        [callback = std::move(typed_callback)](
            void* input, void* output) {
            callback(
                *static_cast<Input*>(input),
                *static_cast<Output*>(output));
        });
}
```

Usage:

```cpp
struct Request
{
    int value{};
};

struct Response
{
    int result{};
};

auto adapter = makeExecutionAdapter<Request, Response>(
    [](Request& request, Response& response) {
        response.result = request.value * 2;
    });

auto input = adapter.createInput();
auto output = adapter.createOutput();
static_cast<Request*>(input.get())->value = 21;

adapter.invoke(input.get(), output.get());
```

The factories and callback cannot accidentally use different types because
they are generated from the same `Input` and `Output` template arguments. This
guarantee assumes `invoke()` receives the objects created by the same adapter;
an unrelated raw pointer can still violate its precondition.

This is generally the best primary guarantee for a typed builder,
registration API, or dependency-injection entrance.

## Use the concept/model type-erasure pattern

Instead of storing independent erased functions, place all related behavior in
one polymorphic model. The concrete model retains its types internally.

```cpp
#include <functional>
#include <memory>
#include <utility>

class ExecutionConcept
{
public:
    virtual ~ExecutionConcept() = default;
    virtual void execute() = 0;
};

template <typename Input, typename Output>
class ExecutionModel final : public ExecutionConcept
{
public:
    using Callback = std::function<void(Input&, Output&)>;

    explicit ExecutionModel(Callback callback)
        : m_callback(std::move(callback))
    {
    }

    void execute() override
    {
        Input input{};
        Output output{};
        m_callback(input, output);
    }

private:
    Callback m_callback;
};
```

Usage:

```cpp
struct Input
{
    int value{10};
};

struct Output
{
    int value{};
};

std::unique_ptr<ExecutionConcept> execution =
    std::make_unique<ExecutionModel<Input, Output>>(
        [](Input& input, Output& output) {
            output.value = input.value + 1;
        });

execution->execute();
```

The virtual interface is erased, but the model never separates creation from
typed invocation. This is the same broad technique used by many value-like
type-erased wrappers.

Use it when the erased abstraction has several related operations or is
naturally represented as an object with virtual behavior.

A private constructor or framework-issued token can additionally prove that
the object came from an approved registration path. That is an access-control
refinement of this pattern, not a separate type-compatibility mechanism.

## Recover polymorphic types with `dynamic_cast`

C++ has a built-in form of runtime type recovery for polymorphic class
hierarchies. When an object is accessed through a base-class pointer or
reference, RTTI retains enough information about its dynamic type for
`dynamic_cast` to verify and perform a safe downcast or cross-cast. The program
does not need to store a separate type identifier: implementation-managed RTTI
is associated with the polymorphic object.

```cpp
#include <iostream>
#include <memory>
#include <string>
#include <typeinfo>
#include <utility>

class Event
{
public:
    virtual ~Event() = default;
};

class TemperatureEvent final : public Event
{
public:
    explicit TemperatureEvent(double value)
        : celsius(value)
    {
    }

    double celsius{};
};

class LogEvent final : public Event
{
public:
    explicit LogEvent(std::string value)
        : message(std::move(value))
    {
    }

    std::string message;
};

void inspect(const Event& event)
{
    if (const auto* temperature =
            dynamic_cast<const TemperatureEvent*>(&event)) {
        std::cout << temperature->celsius << '\n';
        return;
    }

    if (const auto* log = dynamic_cast<const LogEvent*>(&event)) {
        std::cout << log->message << '\n';
    }
}
```

Usage:

```cpp
std::unique_ptr<Event> event =
    std::make_unique<TemperatureEvent>(23.5);

inspect(*event);

auto* temperature = dynamic_cast<TemperatureEvent*>(event.get());
if (temperature != nullptr) {
    temperature->celsius = 24.0;
}
```

For a pointer cast, failure returns `nullptr`. For a reference cast, failure
throws `std::bad_cast`:

```cpp
try {
    TemperatureEvent& temperature =
        dynamic_cast<TemperatureEvent&>(*event);
    temperature.celsius = 25.0;
} catch (const std::bad_cast&) {
    // The object is not a TemperatureEvent.
}
```

This is type erasure through a polymorphic base: callers can store and
transport an `Event` without knowing the concrete derived class, then recover
a specific compatible type safely. Unlike an unchecked `static_cast`,
`dynamic_cast` verifies the relationship using the object's runtime type
information.

Its scope is intentionally limited:

- The source must be a pointer or reference to a polymorphic class when runtime
  checking is required; such a class normally has at least one virtual
  function.
- The possible target class must still be named in C++ code at compile time.
- It works with class inheritance relationships, not arbitrary values stored
  behind `void*`.
- RTTI must be enabled in the build.
- Across shared-library boundaries, all components must have compatible ABI
  and consistent type definitions.

Therefore, `dynamic_cast` is a strong built-in choice when the erased
abstraction is naturally an open class hierarchy. Use `std::type_index`,
`std::any`, stable descriptors, or another explicit mechanism when types are
unrelated, selected only from runtime metadata, or exchanged across ABI or
process boundaries.

## Attach runtime type identity with `std::type_index`

For dynamic in-process composition, retain the concrete C++ type as runtime
metadata and verify it before casting.

```cpp
#include <memory>
#include <stdexcept>
#include <typeindex>
#include <utility>

struct ErasedValue
{
    std::shared_ptr<void> owner;
    std::type_index type{typeid(void)};

    template <typename T>
    static ErasedValue make(T value)
    {
        return {
            std::make_shared<T>(std::move(value)),
            std::type_index(typeid(T))};
    }

    template <typename T>
    T& get()
    {
        verify<T>();
        return *static_cast<T*>(owner.get());
    }

    template <typename T>
    const T& get() const
    {
        verify<T>();
        return *static_cast<const T*>(owner.get());
    }

private:
    template <typename T>
    void verify() const
    {
        if (type != std::type_index(typeid(T))) {
            throw std::runtime_error("erased value type mismatch");
        }
    }
};
```

Usage:

```cpp
ErasedValue value = ErasedValue::make<int>(42);

int& number = value.get<int>();  // Valid.
// value.get<double>();          // Throws instead of invalid casting.
```

This converts undefined behavior into a controlled runtime error.

`std::type_index` is appropriate primarily inside one C++ process. It should
not be treated as a portable, stable identity across independently built
plugins, ABI boundaries, processes, or machines.

## Use `std::any` for checked value erasure

`std::any` stores both a value and its runtime type. `std::any_cast` performs a
checked recovery.

```cpp
#include <any>
#include <iostream>
#include <string>

void printString(const std::any& value)
{
    const auto& text = std::any_cast<const std::string&>(value);
    std::cout << text << '\n';
}
```

Usage:

```cpp
std::any value = std::string("hello");
printString(value);  // Valid.

// std::any wrong = 42;
// printString(wrong);  // Throws std::bad_any_cast.
```

This is useful when values are heterogeneous and performance is not dominated
by erased access. A mismatch is observable, but validation occurs at runtime
and exception handling must be part of the boundary policy.

## Use `std::variant` for a closed set of types

If all supported types are known in advance, a tagged union keeps full type
safety without unchecked casts.

```cpp
#include <iostream>
#include <string>
#include <variant>

using Value = std::variant<int, double, std::string>;

void print(const Value& value)
{
    std::visit(
        [](const auto& typed_value) {
            std::cout << typed_value << '\n';
        },
        value);
}
```

Usage:

```cpp
Value first = 42;
Value second = std::string("typed");

print(first);
print(second);
```

The compiler and variant tag guarantee that the visitor receives the active
type. This is preferable to open-ended type erasure when the type set is
intentionally closed.

## Validate stable type or schema descriptors

Across plugin, shared-library, process, or wire boundaries, use an identity
that is stable outside one C++ compilation unit. A descriptor can contain a
canonical name, schema hash, version, serialization format, or registered
UUID.

A single erased value type can carry both its `void` storage and the descriptor
of the concrete `T` that was erased:

```cpp
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

struct TypeDescriptor
{
    std::string canonical_name;
    std::uint64_t schema_hash{};
    std::uint32_t version{};

    friend bool operator==(
        const TypeDescriptor& left,
        const TypeDescriptor& right)
    {
        return left.canonical_name == right.canonical_name &&
               left.schema_hash == right.schema_hash &&
               left.version == right.version;
    }
};

template <typename T>
TypeDescriptor descriptorOf();

class ErasedValue
{
public:
    template <typename T>
    static ErasedValue make(T&& value)
    {
        using Stored = std::decay_t<T>;

        return ErasedValue(
            std::make_shared<Stored>(std::forward<T>(value)),
            descriptorOf<Stored>());
    }

    [[nodiscard]] bool sameType(const ErasedValue& other) const
    {
        return m_type == other.m_type;
    }

    [[nodiscard]] const TypeDescriptor& type() const noexcept
    {
        return m_type;
    }

    template <typename T>
    const T& get() const
    {
        if (!(m_type == descriptorOf<T>())) {
            throw std::runtime_error("erased value type mismatch");
        }

        return *static_cast<const T*>(m_owner.get());
    }

private:
    ErasedValue(std::shared_ptr<void> owner, TypeDescriptor type)
        : m_owner(std::move(owner)),
          m_type(std::move(type))
    {
    }

    std::shared_ptr<void> m_owner;
    TypeDescriptor m_type;
};
```

Usage:

```cpp
#include <iostream>

struct Image
{
    int width{};
};

struct Command
{
    int opcode{};
};

template <>
TypeDescriptor descriptorOf<Image>()
{
    return {
        "example.Image",
        0x9a3f7c21d80b1142ULL,
        1};
}

template <>
TypeDescriptor descriptorOf<Command>()
{
    return {
        "example.Command",
        0xb1718d61c09007aeULL,
        1};
}

ErasedValue first_image = ErasedValue::make(Image{1920});
ErasedValue second_image = ErasedValue::make(Image{1280});
ErasedValue command = ErasedValue::make(Command{7});

bool images_match = first_image.sameType(second_image);  // true
bool command_matches = first_image.sameType(command);    // false

const Image& image = first_image.get<Image>();  // Valid.
std::cout << image.width << '\n';

// Descriptor validation throws before an invalid static_cast can occur.
// const Command& wrong = first_image.get<Command>();
```

There is only one erased representation: `ErasedValue`. Its private
constructor ensures that `make<T>()` stores the descriptor and allocation for
the same concrete `T`. Two erased values can be compared without recovering
either concrete type, and `get<T>()` validates the requested stable descriptor
before performing the hidden cast.

An erased callback can therefore accept only `ErasedValue` and recover its
expected type safely:

```cpp
void inspectImage(const ErasedValue& value)
{
    const Image& image = value.get<Image>();
    std::cout << image.width << '\n';
}
```

## Choosing a compatibility mechanism

| Composition model | Preferred guarantee |
| --- | --- |
| Types known together at registration | One typed builder generates every related erased operation |
| Several coupled operations owned by one object | Concept/model type erasure |
| Open polymorphic class hierarchy | `dynamic_cast` and RTTI |
| Unrelated values inside one compatible C++ process | `std::type_index` or `std::any` |
| Closed set of alternatives | `std::variant` |
| Plugins, shared libraries, processes, or wire protocols | Stable type or schema descriptor |

The strongest design establishes compatibility as early as possible. Prefer a
typed builder or model when the types are available together. When composition
must happen dynamically, carry enough trustworthy runtime identity to validate
the connection before any erased pointer is cast.
