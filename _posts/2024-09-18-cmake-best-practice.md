---
layout: post
title:  "CMake: Best Practice(bp)"
date:   2024-09-18 09:22:46 +0800
tags: [c++]
---

It has been a long time since I want to summarize the usage of CMake and give a best practice for using it. Recently I have time to read the book: [Professional CMake: A Practical Guide](https://crascit.com/), and it's time to do this. CMake is complex and easy at the same time: it's complex because what it tries to solve is complex; it's easy because once we know how to use it and familiar with the best practice, it's basically repitition afterwards. So the key here is to have a model for repetition, which I try to give here. 

All code can be found at repo: [best_practice_lib](https://github.com/shan-weiqiang/cmake/tree/main/best_practice_lib). 

For easy understanding of the repo, the project composition is like following:

![alt text](/assets/images/cmake_best_practice.png)

After build and installation, the package looks like following:

```shell
➜  install git:(main) tree                                     //<install folder>
.
├── bin                                                        //executables folder
│   ├── computer -> computer-1.0.0
│   └── computer-1.0.0
├── include                                                    // header files folder
│   ├── caculator
│   │   └── caculator.h
│   ├── divide
│   │   └── divide.h
│   ├── json.hpp
│   └── multi
│       └── multi.h
└── lib
    ├── cmake                                                   // folder for cmake scripts
    │   └── bp
    │       ├── bpConfig.cmake                                  // package level cmake
    │       ├── bpConfigVersion.cmake                           // package level version cmake(package only)
    │       ├── Caculator                                       // Caculator component
    │       │   ├── CaculatorConfig.cmake
    │       │   └── CaculatorConfig-noconfig.cmake
    │       ├── Computer                                        // Computer component
    │       │   ├── ComputerConfig.cmake
    │       │   └── ComputerConfig-noconfig.cmake
    │       ├── Json                                            // Json component
    │       │   └── JsonConfig.cmake
    │       └── Math                                            // Math component
    │           ├── MathConfig.cmake
    │           └── MathConfig-noconfig.cmake
    ├── libCaculator.so -> libCaculator.so.3                    // libraries in unix version format  
    ├── libCaculator.so.3 -> libCaculator.so.3.2.1
    ├── libCaculator.so.3.2.1
    ├── libdivide.so -> libdivide.so.3
    ├── libdivide.so.3 -> libdivide.so.3.2.1
    ├── libdivide.so.3.2.1
    ├── libmulti.so -> libmulti.so.3
    ├── libmulti.so.3 -> libmulti.so.3.2.1
    └── libmulti.so.3.2.1
```

Consumers can use above package and components and specify versions like:

```cmake
find_package(bp 2.1.0 EXACT COMPONENTS Caculator)
```
Examples can be found at: [best_practice_client](https://github.com/shan-weiqiang/cmake/tree/main/best_practice_client)

What really matters:

- All target dependencies are managed automatically. For example when client use `Math::Caculator` component, it's dependency `Math::divide`, `Math::multi`, and their dependencies `nlomann::json` and `foonathan_memory` will be automatically discovered. If the dependencies are not met, error will happen during configuration time and give proper messsages.
- Support `QUIET` option for package

Detailed usage and their nationale are given inside the repo as comments. The repo will be continously updated in the future, such as `ctest`, `cpack` will be added.

