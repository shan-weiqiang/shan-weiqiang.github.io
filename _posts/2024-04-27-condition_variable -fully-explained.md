---
layout: post
title:  "std::condition_variable: a deeper look"
date:   2024-04-27 19:22:46 +0800
tags: [c++]
---


This post tries to enumerate the pitfalls that might happen in the use of `condition_variable`. First I will explain scenarios in the use of `condition_variable`; then give a summary about tips of using it; At the end of the post, a live example is given to demonstrate what have been talked about in this post. Hope this will help someone to spent one less miniute debugging `condition_variable`.

* toc
{:toc}

# Thread flow

To understand `condition_variable`, we assume following premises:

- There is only one notifying thread
- There is only one waiting thread
- The notify_one/notify_all will only be called once
- The condition is atomic bool

You might think these premises are too much and what's the point of analysing it with so many premises. As it turns out, even with these premises, the situation is so complicated that it deserves efforts to understand it. Besides, after we are clear about this, we can understand all situations that are not bounded by those premises.

## Waiting thread

`condition_variable` is implemented on `futex` in Linux, I will not go deeper about it at here, it's too big a topic, more info can be found [here](https://man7.org/linux/man-pages/man2/futex.2.html). All we need to know in this blog is following:

- Iniside the `wait` function call, the mutex associated with it will be unlocked before blocking
- The unlock of the mutex and the changing to block state is done atomically
- After wake up of the blocking thread, the thread will first tries to lock the associated mutex, before return

Following is the diagram showing the state of the waiting thread:

![Alt text](/assets/images/waiting.png)

In this diagram:

- `Var` is the atomic *condition*
- `mtx` is the mutex
- The grey area is area that are protected by the `mtx`
- The `CP1` to `CP8` are checkpoints to indicate where the waiting thread might possibly be when the notifying thread calls `notify_one/notify_all`
- The `CPb` means block state, it is done atomically with `CP4`, here I draw it specifically to demonstrate this point
- The dashed rectangular is to indicate the `wait(..)` function call. Note that inside this function call, there is unlock and lock of the `mtx`
- Also I draw a loop, which is a typical use of the waiting thread, which might be is inside a infinite `while` loop


## Notifying thread

The notifying thread is the thread that changes the *condition* and calls `notify_one/notify_all`. We consider all the three possible way of calling these methods:

- Without holding the `mtx` at all
- Holding the lock while changing the *condition* only
- Holding the lock while changing the *condition* and calling `notify_one/notify_all`

Following diagrams show the different ways of calling `notify_one/notify_all`:

![Alt text](/assets/images/notifying.png)

Note the `T1` to `T3` in the diagram, which indicate the time between the changing of the *condition* and the calling of the `notify_one/notify_all`. As you will see ,what happens inside these time intervals are of crucial importance in deciding the final behavior.

## The matrix

Image that there is one notifying thread and one waiting thread like in our premises. When the notifying thread calls `notify_one/notify_all`, what is supposed to happen in our three ways of notifying? Will the waiting thread behaves as expected after the calling of `notify_one/notify_all`? 

It turns out that these are really complex questions and it needs a matrix to express all the possibilities:

![Alt text](/assets/images/matrix.png)

Just like said earlier, what happens between *modifying of the condition* and *calling of `notify_one/notify_all`* is crucial to understand this table. Let's explain all the possibilities one by one.

### T1 scenario

In this scenario, the notifying thread and waiting thread are not influenced by each other through the `mtx`(even though the *condition* itself is atomic, it does not change the result here). When the notifying thread calls `notify_one/notify_all`, the waiting thread might be in:

- `CP1`: This is OK, since the *condition* has been changed by notifying thread
- `CP2`: This is OK, same as `CP1`
- `CP3`: This need a litte more words. Here means the check of *condition* fails, which indicate that the waiting thread checked the *condition* before changing of the *condition* by the notifying thread. The waiting thread will go to blocking state and miss the notification by the waiting thread. As the promise says that our notifying thread will notify only once, this means that the waiting thread will wait forever!
- `CP4`, `CPb`: Behave as expected, since waiting thread already in blocking state and the notification will work as usual.
  > `CP4` and `CPb` are completed atomically! They can be seen as same state, I intentionally split into two checkpoints to demonstrate this point.
- `CP5`, `CP6`: Not possible, since the premise says that there is only one notification call.
- `CP7`~`CP8`: This is OK, the waiting thread check the *condition* after it has been changed by notifying thread.

### T2 scenario

The notifying thread hold the mutex when changing the *condition*, which means:

- During the time interval `T2`, waiting thread must start at *unlock* state of the `mtx`, namely, `CP1` and `CP8`:

Let's discuss all the checkpoints case by case:

- `CP1`: This is OK
- `CP2`: This is OK, waiting thread get the lock after notifying thread releasing the lock
- `CP3`: This is **NOT** possible! This is the trickist part of all situations. Let me explain it step by step:
  - If at the time of the notifying thread calling `notify`, the waiting thread is at `CP3`, the waiting thread might hold the `mtx` **before** or **after** the notifying thread's holding of the lock when changing the *condition*
    - **Before** case: it should have go on to `CP4`, so it's a contradiction
    - **After** case: it is not possible since the *condition* had already been changed when waiting thread get the `mtx`, it should have go to `CP7`, instead of `CP3`!!
- `CP4`, `CPb`: This is OK. This happens if waiting thread check the *condition* before it being changed. It works as usual, the waiting thread will be woken up.
- `CP5`, `CP6`: Not possible, since the premise says that there is only one notification call.
- `CP7`~`CP8`: This is OK, the waiting thread check the *condition* after it has been changed by notifying thread.

### T3 scenario

The waiting thread changes the *condition* and call `notify_one/notify_all` while holding the `mtx`.

- `CP1`: This is OK
- `CP2`: Not possible, since when calling `notify_one/notify_all`, notifying thread is holding the `mtx`
- `CP3`: Same as `CP2`
- `CP4`, `CPb`: This is OK. This happens when the waiting thread is firstly get the `mtx` and go to blocking state; then the notifying thread get the `mtx`. In this situation, the waiting thread will be woken from the kernel, but immedidately be blocked since the notifying thread is holding the lock. Only after the notifying thread release the lock, the waiting thread will be woken again to get the same lock.
- `CP5`: Not possible, since the premise says that there is only one notification call.
- `CP6`: Not possible, same reason as `CP5`. Even without the same reason for `CP5`, `CP6` is also impossible, since notifying thread is holding the same lock.
- `CP7`: Not possible, since notifying thread is holding the same lock
- `CP8`: Not possible, since the premise says that there is only one notification call. There is no way the waiting thread has already passed the *condition* by now

# Golden rules

1. Always use `condition_variable` with a *condition*, otherwise there is no way to check whether it's a spurious wake up or not
2. Use the same lock to protect:
   1. Anything that might change the *condition*, even when the *condition* itself is atomic. As the analysis above, the atomic nature of the *condition* does not change the analysing results.
   2. Anytime checking the *condition*
   3. The *futex*(realized by passing it to `wait(..)`)

# Real world example

Following is an implementation of thread pool, it basically shows every respect of the usage of `condition_variable`:

```cpp
#include <cstddef>
#include <iostream>
#include <condition_variable>
#include <mutex>
#include <queue>
#include <functional>
#include <thread>
#include <vector>

/// In this example the expression: stop || !tasks.empty() is the 'condition' between notifying
/// thread and waiting thread. The condition is used to avoid spurious wakeups. Every time the notifying
/// thread wants to do something that modifies the result of the condition, the mutex must be aquired.
/// The notify_one/notify_all can be called during the hold of the mutex, or can be called after the
/// release of the mutex, the difference is that if called during the hold of the lock, the waiting thread
/// will immediately blocked to wait for the release of the mutex by the calling thread here.

class ThreadPool {
  public:
    ThreadPool(std::size_t thread_num) : stop(false) {
        for (int i = 0; i < thread_num; i++) {
            threads.emplace_back(std::thread(&ThreadPool::thread_func, this));
        }
    }
    ~ThreadPool() {
        // aquire lock before changing the condition
        {
            std::unique_lock<std::mutex> lock(m);
            stop = true;
        }

        cv.notify_all();
        for (auto &thread : threads) {
            thread.join();
        }
    }
    template <typename F>
    void submit_task(F &&func) {
        // aquire lock before changing the condition
        {
            std::unique_lock<std::mutex> lock(m);
            tasks.emplace(std::forward<F>(func));
        }
        // call notify_all after release the lock; this will prevent the waiting thread from immediate block
        // after wake up
        cv.notify_one();
    }

  private:
    void thread_func() {
        while (true) {
            std::function<void()> task;
            {
                std::unique_lock<std::mutex> lock(m);
                // wait for the condition to be true; condition is required. If no condtion, waiting thread
                // can not decide it's spurious wake-up or not
                cv.wait(lock, [this]() { return stop || !tasks.empty(); });
                if (stop && tasks.empty()) {
                    return;
                }
                // protected under the mutex, since these steps will change the condition
                task = std::move(tasks.front());
                tasks.pop();
            }
            // do not influence the condition, do it without holding the mutext
            task();
        }
    }
    std::queue<std::function<void()>> tasks;
    // This mutex is used for three purpose and these three purposes must be protected under this same mutex:
    // 1. Protect the tasks queue
    // 2. Protect the stop condition
    // 3. Protect the condition variable(which is a futex)
    // 1 and 2 both influence the result of the condition; 3 is required by the futex implementation in syscall
    std::mutex m;
    std::condition_variable cv;
    bool stop;
    std::vector<std::thread> threads;
};

int main() {
    // used to sync std::cout
    std::mutex m;
    ThreadPool pool(4);
    for (int i = 0; i < 8; i++) {
        pool.submit_task([i, &m]() {
            std::lock_guard<std::mutex> lock{m};
            std::cout << "Task " << i << " is running\n";
        });
    }
    std::this_thread::sleep_for(std::chrono::seconds(5));

    pool.submit_task([&m]() {
        std::lock_guard<std::mutex> lock{m};
        std::cout << "This is the last task" << std::endl;
    });

    return 0;
}

```