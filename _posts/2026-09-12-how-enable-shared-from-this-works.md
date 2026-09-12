---
layout: post
title:  "How std::enable_shared_from_this Works"
date:   2026-09-12 10:00:00 +0800
tags: [cpp, smart-pointers, memory-management, crtp]
---

`std::enable_shared_from_this<T>` lets an object obtain a `shared_ptr` to
itself without creating a second ownership group. The returned `shared_ptr`
shares the control block that already owns the object.

![How enable_shared_from_this connects an object to its shared ownership control block](/assets/images/enable_shared_from_this_workflow.png)

* toc
{:toc}

## 1. CRTP supplies the object type

A class derives from `enable_shared_from_this` specialized with itself:

```cpp
#include <memory>

class Foo : public std::enable_shared_from_this<Foo> {
public:
    [[nodiscard]] std::shared_ptr<Foo> get_shared()
    {
        return shared_from_this();
    }
};
```

This CRTP relationship tells the base class which pointer type to return. A
simplified model of the base contains a `weak_ptr<Foo>` that will later refer
to the object's ownership control block. It does not contain another `Foo`.

## 2. shared_ptr establishes the connection

Object construction and ownership setup are separate operations:

```cpp
const auto owner = std::make_shared<Foo>();
```

Conceptually, `make_shared<Foo>()` performs these steps:

1. Allocate storage for the control block and `Foo`.
2. Construct `Foo`; its inherited weak pointer is initially empty.
3. Connect that weak pointer to `Foo` and the new control block.
4. Return the owning `shared_ptr<Foo>`.

The connection is established by the `shared_ptr` machinery after the `Foo`
constructor finishes. It is weak, so it does not increase the strong reference
count or create a self-ownership cycle.

## 3. shared_from_this acquires a strong reference

After ownership has been established, the object can promote its inherited
weak pointer:

```cpp
const auto owner = std::make_shared<Foo>();
const auto self = owner->get_shared();
```

`owner` and `self` point to the same `Foo` and share the same control block.
Creating `self` increases the strong reference count; it does not create a new
control block.

Conceptually, `shared_from_this()` constructs a `shared_ptr<Foo>` from the
inherited weak pointer. The standard library manages that weak pointer; it is
not a public data member.

## When shared_from_this fails

If no live `shared_ptr` has established the weak connection,
`shared_from_this()` throws `std::bad_weak_ptr`:

```cpp
Foo foo;
const auto self = foo.get_shared();  // Throws std::bad_weak_ptr.
```

An object owned only by `unique_ptr` has the same problem:

```cpp
const auto owner = std::make_unique<Foo>();
const auto self = owner->get_shared();  // Throws std::bad_weak_ptr.
```

Calling `shared_from_this()` from the object's constructor is also too early.
With `make_shared<Foo>()`, the weak connection is not established until after
construction of `Foo` has finished.

Since C++17, `weak_from_this().lock()` provides a non-throwing alternative:

```cpp
const auto self = weak_from_this().lock();
if (!self) {
    // No live shared ownership has been established.
}
```

It returns an empty `shared_ptr` when the weak connection is empty or expired.

## The ownership sequence

```text
construct Foo
    -> establish shared ownership and its control block
    -> connect the inherited weak_ptr to that control block
    -> shared_from_this() promotes the weak_ptr
    -> return another shared_ptr in the same ownership group
```

Because the inherited connection is weak, releasing the last strong owner can
still destroy `Foo` normally.

## Do not create another control block

Constructing a new `shared_ptr` directly from `this` does not recover the
existing ownership:

```cpp
std::shared_ptr<Foo> incorrect()
{
    return std::shared_ptr<Foo>{this};
}
```

It creates a second control block for the same object. The two ownership groups
can then attempt to destroy the object independently. Use `shared_from_this()`
to join the existing ownership group.

## Conclusion

`enable_shared_from_this` works through a hidden weak connection. The owning
`shared_ptr` connects that weak pointer to the object's control block, and
`shared_from_this()` promotes it to another strong reference in the same
ownership group.
