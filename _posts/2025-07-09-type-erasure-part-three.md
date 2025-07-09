---
layout: post
title:  "Type Erasure Part Three: The Downside"
date:   2025-07-09 01:00:00 +0800
tags: [c++]
---

I talk about two drawbacks about type erasure: confusing *type erasure* with *object slicing* and the need for manual memory management.

## Confused with Object slicing

*Object slicing* is a different concept. However, it can be confused with *type erasure*:

```c++
class A {
public:
    virtual void foo() { std::cout << "A::foo()" << std::endl; }
    int data_a = 1;
};

class B : public A {
public:
    virtual void foo() override { std::cout << "B::foo()" << std::endl; }
    int data_b = 2;
};

std::vector<A> vec;
B b;
vec.push_back(b);  // Object slicing occurs here
```

Above example has a false indication that `std::vector<A>` can both store objects of type `A` and type `B`. That's not true, since all objects of `B` is *sliced* to become `A`. What if we use `std::vector<std::shared_ptr<A>>`? Does this avoid *object slicing*? The answer is yes and no, because of the resources leakage problem. The final puzzle is a virtual destructor. Let em summarize all possible scenarios:

| Stored as | vdtor | not vdtor |
| --------- | ----- | --------- |
| Objects   | [1]   | [2]       |
| Pointers  | [3]   | [4]       |

Before going deeper, we first clarify one important point: the memories that are allocated during object creation, `new` operation, will be freed during using `delete`, whether it is called manually, or by other means(`std::shared_ptr` will call `delete` for us). Those memory size are stored in metadata during `new`. This means if we using `new` to allocate a object `A`, then cast it to `B`, then `delete` `B`'s pointer, the `delete` will free the size allocated during `new`, not caring about `B`'s impact, which will have many implications. We here differentiate two types of resources:

1. Memory blocks allocated using `new`, we call it *memory block*.
2. Other resources managed by the object itself, we call it *dynamic resources*, such as heap memories, file descriptors.

Ok now let's discuss one by one:

1. Stored as objects and with virtual destructors: object slicing happens. The derived class's destructor will be called on the sliced object and `delete` operator will also operate on the sliced object, both of which are *undefined behavior* due to the memory slicing.
2. Stored as objects and without virtual destructors: object slicing happens. The base class's destructor will be called on the sliced object, which is ok. But the dynamic resoruces managed by the derived class will be not released. `delete` operator will operate on sliced objects, which is UB.
3. Stored as pointers and with virtual destructor: everything is ok. `delete` will free memory block and virtual destructor will properly manage dynamic resources.
4. Stored as pointers and without virtual destructor: `delete` will work fine since there are no object slicing. But the dynamic resources managed by the derived class will not be properly released.

The only way is to store a pointer and use virtual destructor. The virtual destructor is not the same as other virtual functions. It will *always* be called during destruction phase, so it must be implemented, even it is a pure virtual function. The virtual property of destructor assures that the derived class's destructor always be called, hence release the relvent dynamic resources.

## Manual Memory Management

Due to the fact that type is erased, what if user wants to copy, create, move a type erased object? With type information these can be done easily, but with type erased, we do not know the exct type anymore. So we have to manually create these operations. Here is an example:

```c++
#include <iostream>
#include <vector>

// Example classes to test with
class A {
public:
    void foo() { std::cout << "A::foo()" << std::endl; }
};

class B {
public:
    void foo() { std::cout << "B::foo()" << std::endl; }
};

class TypeErased {
    struct Concept {
        virtual ~Concept() = default;
        virtual void foo() = 0;
        virtual Concept* clone() const = 0;
    };
    
    template<typename T>
    struct Model : Concept {
        T data;
        Model(T x) : data(std::move(x)) {}
        void foo() override { data.foo(); }
        Concept* clone() const override { 
            return new Model(data);
        }
    };
    
    Concept* ptr;
    
public:
    // Constructor
    template<typename T>
    TypeErased(T x) : ptr(new Model<T>(std::move(x))) {}
    
    // Destructor
    ~TypeErased() { 
        delete ptr; 
    }
    
    // Copy Constructor
    TypeErased(const TypeErased& other) : ptr(other.ptr->clone()) {}
    
    // Copy Assignment Operator
    TypeErased& operator=(const TypeErased& other) {
        if (this != &other) {
            delete ptr;
            ptr = other.ptr->clone();
        }
        return *this;
    }
    
    // Move Constructor
    TypeErased(TypeErased&& other) noexcept : ptr(other.ptr) {
        other.ptr = nullptr;
    }
    
    // Move Assignment Operator
    TypeErased& operator=(TypeErased&& other) noexcept {
        if (this != &other) {
            delete ptr;
            ptr = other.ptr;
            other.ptr = nullptr;
        }
        return *this;
    }
    
    // Member function
    void foo() { ptr->foo(); }
};

int main() {
    std::cout << "=== Testing all special member functions ===" << std::endl;
    
    // Constructor
    TypeErased obj1(A{});
    std::cout << "obj1: ";
    obj1.foo();
    
    // Copy Constructor
    TypeErased obj2(obj1);
    std::cout << "obj2 (copy of obj1): ";
    obj2.foo();
    
    // Copy Assignment
    TypeErased obj3(B{});
    std::cout << "obj3: ";
    obj3.foo();
    
    obj3 = obj1;  // Copy assignment
    std::cout << "obj3 (after copy assignment): ";
    obj3.foo();
    
    // Move Constructor
    TypeErased obj4(std::move(obj2));
    std::cout << "obj4 (moved from obj2): ";
    obj4.foo();
    
    // Move Assignment
    TypeErased obj5(B{});
    std::cout << "obj5: ";
    obj5.foo();
    
    obj5 = std::move(obj4);  // Move assignment
    std::cout << "obj5 (after move assignment): ";
    obj5.foo();
    
    // Test with containers
    std::vector<TypeErased> vec;
    vec.push_back(A{});  // Uses move constructor
    vec.push_back(B{});  // Uses move constructor
    
    std::cout << "\nVector elements:" << std::endl;
    for (auto& item : vec) {
        item.foo();
    }
    
    return 0;
}
```

In this example, both type A and type B provides `foo` method, we use the `TypeErased` to erase the type information, user does not need to know A or B, or anyother classes that have method `foo`. 
