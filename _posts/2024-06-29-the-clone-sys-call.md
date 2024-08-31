---
layout: post
title:  "arguments of clone() system call"
date:   2024-06-30 10:20:46 +0800
tags: [linux-programming]
---

This blog reference most of it's content to Chapter 28.2 of [The Linux Programming Interface](https://man7.org/tlpi/)

`clone()` system call has following signature:

```c
int clone(int (*func) (void *), void *child_stack, int flags, void *func_arg, ... /* pid_t *ptid, struct user_desc *tls, pid_t *ctid */ );
```
`func` is the address of the entry function; `child_stack` is the starting pointer on which the new function's stack will be built; `flags` are sets of bit masks that are used to specify the behaviors of this `clone` operation. We focus on some of the flags. Before starting to delve into the discussion of specific flags, it's useful to have a general understanding of what is `process` and `thread` in linux. As far as i read, following quote from the book [The Linux Programming Interface](https://man7.org/tlpi/) have the most concise and accurate description:

> At this point, it is worth remarking that, to some extent, we are playing with
words when trying to draw a distinction between the terms thread and process. It
helps a little to introduce the term *kernel scheduling entity* (KSE), which is used in
some texts to refer to the objects that are dealt with by the kernel scheduler. Really,
threads and processes are simply KSEs that provide for greater and lesser degrees
of sharing of attributes (virtual memory, open file descriptors, signal dispositions,
process ID, and so on) with other KSEs. The POSIX threads specification provides
just one out of various possible definitions of which attributes should be shared
between threads.

I could not describe the difference and relationship between `process` and `thread` better than this quote, so no more words about `process` and `thread`. Let's go into some of the flags. Different flags combinations in the `clone()` call will create different KSEs that will share resources with the calling KSE in different level and aspects. In following discussion we avoid using `process` and `thread` to prevent ambiguity, instead KSE is used to denote the returned entity by `clone()`

# CLONE_FILES

If specified the returned KSE shares the same table for descriptors, which means that file descriptor creation and deallocation is visible between each other. For example, if in the calling KSE there is a new `socket` created, it will be automatically usable in the returned KSE. This flag makes the calling KSE and the returned KSE not only share the *file description*, but also the *file descriptor*. Please note the difference: file descriptions can be referenced by *multiple* file descriptors, both in same process or in different process. If this flag is not specified, the returned KSE will have a *copy* of the calling KSE's file descriptor table, which will increment the reference count for the file description that the file descriptors point to. In this scenario, two different file descriptors point to the same file description(system wide resource), and they share the properties that are decided by the file description, like read/write positions, but they are different file descriptors. If inside one KSE, the file descriptor is closed, the file descriptor in another KSE is still usable. But if CLONE_FILES is specified, the calling KSE and the returned KSE share the same file descriptor, not copy.

# CLONE_FS

If specified, calling KSE and returned KSE share current working directory and root directory. If any one of them changes those value, the other one sees them. Again, if not specified, the returned KSE have a copy for that of the calling KSE and after the copy, they will have individual working directory and root directory, with change of them not affecting each other.

# CLONE_VM

If specified, the calling KSE and the returned KSE share the same virtual memory table. Otherwise, the returned KSE get a copy of the calling KSE's virtual table, like in `fork()`

# CLONE_SIGHAND

If specified, the calling KSE and the returned KSE share the same handling behavior for every signal. If not specified, the returned KSE get a copy of current behavior from the calling KSE, but when any of them changes the signal behavior, the other one can not see it. 

Pending signals and signal masks are NOT shared between the calling KSE and the returned KSE, even if this flag is specified. panding signals and signal masks are KSE specific.

Imagine that this flag is specified and both KSE share the same signal handler, when one of them changes the handler, so the handler address is changed, what happens if the other KSE get the signal and need to call this handler(which is changed by another KSE to a different address)?  The only way this works is that the two KSEs must have same virtual memory address. Say if one of the KSE load some library into the virtual memory and changes the handler address to this memory region, if the two KSEs share the same virtual memory, the other one can safely calls the handler, otherwise segmentation fault is supposed to happen. So if CLONE_SIGHAND is specified, CLONE_VM must also be specified.


# CLONE_THREAD

If specifed the returned KSE have the same thread group ID as the calling KSE, otherwise a new thread group ID is created for the returned KSE. Thread group ID is the same thing as process ID. Following diagram illustrate the relationship between different KSEs and what is POSIX thread:

| ![Alt text](/assets/images/linux_thread_process.png) | 
|:--:| 
| *POSIX thread, KSE, PID/TGID/TID relationship*  |

There some key points about the effect of this flag:

- We can call KSEs created with CLONE_THREAD flag `threads`
- No signals is sent to the calling KSE when `thread` is terminated, so `thread` can not be waited like `process`; the right way to *wait* a `thread` to terminate is throuth the `join()` semantics. The cornerstone behind the `join` is *futex*, which we dicuss in [futex](https://shan-weiqiang.github.io/2024/06/08/futex-syscall-foundation-for-mutex-and-semaphore.html). For how the `join` works and the behaviors of the `join`, i will write another blog. For now we need to konw that `thread` created with CLONE_THREAD can not be waited using `wait()/waitpid()`  and must use `join` to wait for it
- When all KSEs inside one TGID(PID) terminate, a SIGCHLD signal is sent to parent process of this TGID
- If any `thread` inside one thread group calls `exec()`, all other threads except for the thread group leader are terminated and the new program is executed inside the thread group leader
- If any `thread` inside one thread group calls `fork`, anyother `thread` inside this thread group can call `wait` on it
  - `fork` only have something to do with the calling `thread`, except for the `wait` operation above, other `thread` does not have much to do with the forked process
- If CLONE_THREAD is specified, CLONE_SIGHAND must be specifed, again CLONE_VM must be specifed

# CLONE_PARENT_SETTID/CLONE_CHILD_SETTID/CLONE_CHILD_CLEARTID

Those are flags to support POSIX threads. 

- CLONE_PARENT_SETTID: `clone` will set the ID of the returned KSE to the parameter `pid_t *ptid`. The value is the same as the return value of `clone`. 
  - The set of the value happens before the duplication of virtual memory, so even the CLONE_VM not specified, the child and parent both can see the newly created `pid`. CLONE_VM is required for POSIX threads
  - Getting `pid` through parameter and through the return value is different: for example, if the returned KSE terminates immediately *before* the parent has the chance to do the assignment of the return value, and if the SIGCHLD handler in parent use the `pid`, the `pid` is invalid, because the `pid` has not been assigned yet. But if the `pid` is aquired by argument `ptid`, due to the fact that the write of the `pid` to `ptid` is done before the `clone` returns, the parent SIGCHLD handler can safely use this `pid`
- CLONE_CHILD_SETTID: `clone` write the ID of the newly created KSE into the child's memory location specified by argument `pid_t *ctid`.  Note that if CLONE_VM is specified, this will also affect the parent. For POSIX threads, CLONE_VM must be specified. So for the POSIX thread implmentation, CLONE_PARENT_SETTID and CLONE_CHILD_SETTID  overlapps in functionality
- CLONE_CHILD_CLEARTID: `clone` zeros the memory pointed by `pid_t *ctid`

## pthread_join under the hood

In linux, the `pthread_join/pthread_create` is implemented based on these three flags. When `pthread_create` creates threads, CLONE_PARENT_SETTID and CLONE_CHILD_CLEARTID is used, `pid_t *ptid` and `pid_t *ctid` are set to point to the same location. CLONE_CHILD_SETTID is irrelevent because POSIX thread requires the CLONE_VM. Kernel does the following trick to support POSIX threads:

- Kernel treat the memory pointed to by `pid_t *ptid` and `pid_t *ctid` as [futex](https://shan-weiqiang.github.io/2024/06/08/futex-syscall-foundation-for-mutex-and-semaphore.html)
- When `pthread_join` joins the `pid_t`, it actually `FUTEX_WAIT` on this *futex*, if condition is not met, then calling thread is put into block
- When the KSE terminates, since then CLONE_CHILD_CLEARTID is specified, the *futex* is cleared and `FUTEX_WAKE` is called on this *futex*, which wakes up thread that is waiting on this *futex*. This mechanism achieve the behavior that the `phread_join` calling thread is blocked until the termination of the joined thread denoted by `pid_t`

# CLONE_SETTLS

If specified, the argument `user_desc *tls` is used as thread-local storage. This storage is only accesible by the newly created KSE

# use `clone` to implement `fork` and POSIX threads

`fork` and POSIX threads can be implemented by `clone` with different flags specifed:

- `fork` corresponds to flags combination: `CLONE_VM | CLONE_VFORK | SIGCHLD`
- POSIX threads corresponds to flags combination: `CLONE_VM | CLONE_FILES | CLONE_FS | CLONE_SIGHAND | CLONE_THREAD | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID | CLONE_SYSVSEM`

```cpp
// Demonstrate the use of the clone(..) to simulate fork and std::threads
#include <chrono>
#include <csignal>
#include <cstddef>
#include <ctime>
#include <iostream>
#include <mutex>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

#define STACK_SIZE 65536

void sig_handler(int) { exit(0); }

// mutex to synchronize printf
std::mutex mtx;

// entry function for clone(..)
int clone_func(void *) {
  for (;;) {
    {
      std::lock_guard<std::mutex> lck{mtx};
      std::cout << "clone thread: " << getpid() << std::endl;
    }
    std::this_thread::sleep_for(std::chrono::seconds(1));
  }
}

// level two std::thread function, used to demonstrate that even they are
// created nested, they are peers with the thread that created them
void level_two() {
  for (;;) {
    {
      std::lock_guard<std::mutex> lck{mtx};
      std::cout << "POSIX thread, id: " << std::this_thread::get_id()
                << std::endl;
    }
    std::this_thread::sleep_for(std::chrono::seconds(1));
  }
}

// level one std::thread function
void level_one() {
  auto t = std::thread(level_two);
  t.join();
}

pid_t child_pid;
pid_t parent_pid;

int main(int argc, char *argv[]) {

  std::signal(SIGINT, sig_handler);

  // Stack for the new thread
  char *stack;

  // Top of the stack
  char *stackTop;
  pid_t pid;

  // Allocate memory for the stack
  stack = (char *)malloc(STACK_SIZE);
  if (stack == NULL) {
    exit(EXIT_FAILURE);
  }

  // Calculate the top of the stack
  stackTop = stack + STACK_SIZE;

  // use `ps --pid <pid> -O tid,lwp,nlwp -L` to see the difference
  if (argc > 1) {
    // CLONE_THREAD flag prevent from creating new thread group ID(the same as
    // process ID); this thread will be peers to threads that are created by
    // std::thread
    // emulate the POSIX threads, like std::thread
    pid = clone(clone_func, stackTop,
                CLONE_VM | CLONE_FILES | CLONE_FS | CLONE_SIGHAND |
                    CLONE_THREAD | CLONE_SETTLS | CLONE_PARENT_SETTID |
                    CLONE_CHILD_CLEARTID | CLONE_SYSVSEM,
                &parent_pid, NULL, &child_pid);
    if (pid == -1) {
      exit(EXIT_FAILURE);
    }
  } else {
    // create new thread group ID, aka creating new process ID
    // emulate fork
    pid = clone(clone_func, stackTop, SIGCHLD, NULL);
    if (pid == -1) {
      exit(EXIT_FAILURE);
    }
  }

  {
    std::lock_guard<std::mutex> lck{mtx};
    printf("Parent process: Created child thread with PID = %d\n", pid);
    printf("Parent process: PID = %d\n", getpid());
  }

  // standard POSIX comforming threads
  std::vector<std::thread> threads;
  for (int i = 0; i < 2; ++i) {
    threads.push_back(std::thread(level_one));
  }

  // wait for signals
  pause();
}
```