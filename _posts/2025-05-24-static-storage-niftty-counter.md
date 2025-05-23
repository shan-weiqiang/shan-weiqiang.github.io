---
layout: post
title:  "Static Storage and Nifty Counter"
date:   2025-05-23 21:22:46 +0800
tags: [middleware]
---

This is reading notes for [*static initialization order fiasco*](https://en.cppreference.com/w/cpp/language/siof) problem and it's solutions.

[*static storage duration*](https://en.cppreference.com/w/cpp/language/storage_duration) includes:

- Global variables: *external linkage*
- *static* members of a class: *external linkage*
- *static* variables: *internal linkage*
- *static* local variables inside functions: *no linkage*

Since the *static initialization order fiasco* only happens between *static objects* which has *external linkage*, we only consider global variables and static members of a class. I call them *static objects* in following content.

# Initialization and destruction order of static objects

Simply put:

- Inside one translation unit(TU), static objects are initialized in the order of their appearance and deinitialized in reverse order.
- Across TU, the order is unspecified.
- Initialization order:
    - Global variables and *static* class members: Initialization happens before `main`; Deinitialization happens after `main`
    - *static* local variables: initialization at first use and deinitialization after `main`
    - *static* variables inside TU: Initialization happens before `main`; Deinitialization happens after `main`

*static initialization order fiasco* happens when *static objects* across TUs depends on each other:

```c++
// file1.h
class A {
public:
    void doSomething() { /* ... */ }
};
extern A aObj;

// file1.cpp
A aObj;

// file2.h
class B {
public:
    B() { aObj.doSomething(); } // Potential problem: aObj might not be initialized yet
    static B bObj;
};

// file2.cpp
#include "file1.h" 
#include "file2.h"
B B::bObj;

int main() {
  return 0;
}
```
# Construct On First Use Idiom

[*Construction On First Use Idiom*](https://isocpp.org/wiki/faq/ctors#static-init-order-on-first-use) use *static* local variable inside function to avoid the problem. Since *static* local variable inside a function has *no linkage* and is initialized when first used, this will prevent the order problem:

```c++
Fred& x()
{
  static Fred* ans = new Fred();
  return *ans;
}
```

- The `ans` will *never* be destructed, which avoids problem of destruction order. The memory will be freed when process terminates by operating system.

If:

```c++
Fred& x()
{
  static Fred ans;  // was static Fred* ans = new Fred();
  return ans;       // was return *ans;
}
```

If some *static object* that depend on `ans` is destructed after `ans` is destructed, there will be the same problem as *static initialization order fiasco*.

# Nifty Counter Idiom

[*Nifty Counter Idiom*](https://en.wikibooks.org/wiki/More_C%2B%2B_Idioms/Nifty_Counter) can solve both initialization and deinitialization order problem. Here I quote the full explanation:

```c++
// Stream.h
#ifndef STREAM_H
#define STREAM_H

struct Stream {
  Stream ();
  ~Stream ();
};
extern Stream& stream; // global stream object

static struct StreamInitializer {
  StreamInitializer ();
  ~StreamInitializer ();
} streamInitializer; // static initializer for every translation unit

#endif // STREAM_H
```
```c++
// Stream.cpp
#include "Stream.h"

#include <new>         // placement new
#include <type_traits> // aligned_storage

static int nifty_counter; // zero initialized at load time
static typename std::aligned_storage<sizeof (Stream), alignof (Stream)>::type
  stream_buf; // memory for the stream object
Stream& stream = reinterpret_cast<Stream&> (stream_buf);

Stream::Stream ()
{
  // initialize things
}
Stream::~Stream ()
{
  // clean-up
} 

StreamInitializer::StreamInitializer ()
{
  if (nifty_counter++ == 0) new (&stream) Stream (); // placement new
}
StreamInitializer::~StreamInitializer ()
{
  if (--nifty_counter == 0) stream.~Stream ();
}
```
> The header file of the Stream class must be included before any member function can be called on the Stream object. An instance of the StreamInitializer class is included in each compilation unit. Any use of the Stream object follows the inclusion of the header, which ensures that the constructor of the initializer object is called before the Stream object is used.

>The Stream class' header file declares a reference to the Stream object. In addition this reference is extern, meaning it is defined in one translation unit and accesses to it are resolved by the linker rather than the compiler.
The implementation file for the Stream class finally defines the Stream object, but in an unusual way: it first defines a static (i.e. local to the translation unit) buffer. This buffer is both properly aligned and big enough to store an object of type Stream. The reference to the Stream object defined in the header is then set to point to this buffer.
This buffer workaround enables fine-grained control of when the Stream object's constructor and destructor are called. In the example above, the constructor is called within the constructor of the first StreamInitializer object, using placement new to place it within the buffer. The Stream object's destructor is called when the last StreamInitializer object is destroyed.

>This workaround is necessary because defining a Stream variable within Stream.cpp - be it static or not - would define it after the StreamInitializer, which is defined by including the header. Then, the StreamInitializer's constructor would run before theStream's constructor, and even worse, the initializer's destructor would run after the Stream object's destructor. The buffer solution above avoids this.
