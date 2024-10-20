---
layout: post
title:  "memory allocation and construction"
date:   2024-10-10 09:22:46 +0800
tags: [c++]
---

- RAAI overview
  - resource management tree
- construction of object
  - two steps:
    - allocate memory
    - initialization
  - `new` keywords does memory allocation and initialization at the same time
  - `operator new` only allocation memory
  - `placement new` only do initialization
    - `uninitialized_copy`
- destruction of object
  - two steps:
    - destruction
    - deallocate memory
  - `delete` keyword does destruction and memory deallocation at the same time
  - `operator delete` only deallocate memory
  - calling destructor explicitly only do destruction, not free memory
- implementation of allocator
