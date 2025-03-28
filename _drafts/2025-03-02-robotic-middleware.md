---
layout: post
title:  "Robotic middlewares: execution model"
date:   2025-03-09 19:22:46 +0800
tags: [middleware]
---

https://didawiki.cli.di.unipi.it/lib/exe/fetch.php/magistraleinformatica/tdp/tpd_reactor_proactor.pdf

Different robotic middleware have different concept and naming of their own in the definition of execution. However, they are all supposed to run in a thread based high performance multi-core operating system, so under different concept there are same meaning. Even though there is no directly one to one mapping of those different concept, I first try to generalize concepts and then try to map each middleware to these *generalized concepts*, many of which directly comes from one of those middlewares. In this blog, we consider: ROS2, Cyberrt, ETAS AOS, Nvidia DriveWorks.


* toc
{:toc}

# Generalized Concpets

Following *generalized concept* are mainly from Nvidia DriveWorks

- *Atomic unit of Execution(AUE)*: The smallest unit that can be scheduled on CPU/GPU; A C++ callable object; Can not start new thread inside it. This concept is closely related to OS and hardware concept.
- *Atomic Algorithmic unit of Execution(AAE)*: The smallest unit that group an functionality. For example fusion, planning. It groups one or more AEs and act as programming interface to applcation developers. The communication between AEs and AAEs are different:
  - AUE can only communicate with other AEs that are inside the same AAE. They exchange data through shared variables.
  - AAE accept inputs and send output to other AAEs through IPC channels. 
- *Port*: Data transfer channels between AAEs.
- *Graph*: DAG graph composed by AAEs(in AOS, AUE can also construct dag).
- *Graphlet*: Subgraph inside a bigger graph.
- *Component*: One AAE or one graphlet.


# Compare


|                         | DriveWorks                  | AOS                      | Cyberrt              |
| ----------------------- | --------------------------- | ------------------------ | -------------------- |
| AUE[5]                  | Pass                        | Runnable                 | Component(Coroutine) |
| AAE[5]                  | Node[4]                     | Activity[3]              | Node[1]              |
| Port[5]                 | Channel                     | Topic                    | Topic                |
| Graph                   | Node DAG[7]                 | Runnable/Activity DAG[2] | Component DAG        |
| Graphlet                | Subgraph                    | NULL                     | NULL                 |
| Model Format            | JSON(DAG)/YAML(STM)         | YAML                     | NULL                 |
| Compiler                | `nodestub`/`stmcompiler`[6] | `yaaac`                  | NULL                 |
| Deterministic Recompute | Not Found                   | YES                      | NO                   |

Note:

1. Cyberrt Node can be used by multiple Component. It is not the same as Node in DriveWorks or Activity in AOS:
   1. Node in DriveWorks or Activity in AOS *contains* Pass or Runnable respectively, Pass or Runnable can communicate with each other in the same scope of Node or Activity, for example shared class member variables.
   2. Node in Cyberrt *serve* one or multiple Components by providing communication. Component communication in Cyberrt is comparable to Node/Activity communication in DriveWorks and AOS.
2. AOS has DAG both for Runanble and Activity
3. AOS Activity is consisted of a DAG of Runnables
4. DriveWorks Node is consisted of a sequential(default) execution of Pass: [Compute Graph Framework SDK Reference](https://developer.nvidia.com/docs/drive/drive-os/6.0.9/public/driveworks-nvcgf/index.html)
   1. By default, Pass inside one node is sequential. The first Pass check new messages, the last Pass send out messages in this Node: polling, instead of event triggering.
   2. A Pass is mapped to a runnable in STM
5. Those concept will be reflected in C++ code
6. DriveWorks' CGF and STM is two different SKD: [System Task Manager SDK Reference](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/index.html)
7. DAG in DriveWorks is different from DAG in AOS and Cyberrt in that it only dictates **data pipeline**, not **triggering**. In both AOS and Cyberrt, node in DAG are triggered or cyclic, that the arrow in the graph not only indicates data flow, but also about activation. In DriveWorks, it's only about data flow, since all Pass exectuion are periodic in nature.

The different concept leads to different strategy when dealing with those middleware, especially scheduling and determinism. In all of those three middlewares, scheduling both happens at the AUE level. But for deterministic control, DriveWorks and AOS use Node and Activity as control unit, Cyberrt use Component as control unit. 

# DriveWorks STM

[Compute Graph And Constraints](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/stm_compiler_computegraphandconstraints.html)

The CGF and STM in DriveWorks has orthogonal relationship:

- Hyperepochs: It's resource partition and it's periodic. Resources are mutually exclusive between different hyperepochs. Each hyperepoch is scheduled periodically. Each hyperepoch contain mulitiple epochs.
- Epochs: A time slot inside hyperepoch. It belongs to hyperepoch and can have period and frame. Period means the interval between exectuion of the same epoch. Frame means the number of the same epoch inside the hyperepoch. The same epoch inside one hyperepoch are executed sequentially.

Hyperepochs and epochs are concept used to divide compute resources: both hardware and time resources. 

- Client: in STM is a OS process, which can contain one or more `Node` in CGF. Each client contain multiple runnables.
- Runnable: in STM is directly mapped from `Pass` in CGF, which is a AUE. Those runables must be executed in epochs. Each epoch might contain runnables from different client(process). Runnables can only have dependencies inside *the same epoch*, which holds true even they come from different client(process).

Clients and Runnables are concept used to represent compute tasks.

The compute graph(YAMLs) for STM is compiled from CGF(JSON), taking the Node relationship into consideration.

All runnables are scheduled by STM periodically, through the concept of hyperepoch and epoch. Hyperepoch is a rough periodical time and epoch is nested inside hyperepoch:

```yaml
Hyperepochs: 
- 100ms_hyper: # executed every 100ms
    Period: 100ms
    Resources: [CPU1, CPU2, GPU0] # each hyperepoch can have resources
    Epochs: # hyperepoch contain multiple epochs
    - Camera:
        Period: 10ms # Camera epoch will be executed 8 times, with interval 10ms
        Frames: 8
    - Radar:
        Period: 100ms # Radar epoch will be 1 time
    - Planning:
        Period: 33ms
        Frames: 3
- 50ms_hyper:
    Period: 50ms
```

Each epoch can have multiple runnables and they will be run during this epoch time slot. Runnables are defined in compute graph yaml files for `client`:

```yaml
Version: 2.0.0
Drive: # Graph ID
Clients:
- Client0: # Client ID
    Resources: # Client0s internal resources
    # Resource Definition
    Epochs: # Epochs present in this client
    - Perception.Camera: # Epoch Global ID - <HyperepochID.EpochID>
        Runnables: # Runnables present in Perception.Camera
        - ReadCamera: # Runnable ID (Unique inside a client)
        - RunnableN:
    - Perception.Radar:
        Runnables: # Runnables present in Perception.Radar
        - ProcessRadar:
```

```yaml
Clients:
    - Client0:
        Resources:
        CUDA_STREAM:
        - CUDA_STREAM0: GPU0
        Epochs:
        - Perception.Camera: # Camera epoch in Perception Hyperepoch
            Runnables:
            - ReadCamera: # Normal runnable
                WCET: 10us
                Resources:
                - CPU # This runnable runs on a CPU
                Priority: 2
            - PreProcessImage: # Submitter runnable
                WCET: 20ms
                StartTime: 1ms # Starts 1ms after the camera epoch
                Resources: # GPU Submitter needs CPU0 and a stream
                - CPU0
                CUDA_STREAM
                Dependencies: [Client0.ReadCamera] # Depends on
                ReadCamera
                Submits: Client0.PreProcessGPUWork # Mentions
                submittee
            - PreProcessGPUWork: # Submittee runnable
                WCET: 5000ns
                Deadline: 30ms # Hint to schedule this before 30ms
                Resources: [GPU]
                Dependencies:
                    - Client0.PreProcessImage # Optional for submittees
                # Note: Inter-epoch dependencies are currently not
                # supported. Inter-client dependencies are supported.
        - Perception.Radar: # Radar epoch in Perception Hyperepoch
                Runnables:
                - ProcessRadar:
                # Runnable specification...
```

Each runnable(Pass in CGF) in clients(OS processes) is configured in above yaml files and `stmcompiler` compiles them to final statical scheduling manifest. Each client has a thread pool to run all the runnables. STM daemon read the scheduling manifest and controls the execution in each client globally.

[STM](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/stm_introduction.html)

Features:

- A CPU Runnable is represented as a callback function (C/C++) that is registered with the STM run-time. STM maintains a pool of worker threads that will call the clients registered functions at the appropriate offset in the schedule.
- One important aspect of STM is that it ever schedules one single pass per hardware engine - never multiple concurrently. This means that one CPU/GPU at a specific time point only have one job to process, preventing scheduling influence from underlying OS.
- System Task Manager (STM) is a static, centrally-monitored, OS-agnostic, non-preemptive user-space scheduler that manages the work across hardware engines. Based on the information from the DAG, a schedule configuration, and the worst-case execution time (WCET) for each pass the STM compiler generates a static schedule. 
  - STM need WCET time to generate static configuration, it is a time-buget system!
  - After WCET is determined, STM can deterministically schedule all runnables
  - STM is non-preemptive, so internally it have to control the statically determined execution order. This implies that it can only keep the results deterministic, but not for the actual execution time.
  - STM master works at the SOC level, controlling all clients(processes) in the SOC. This way all compute engine(CPU/GPU) are coordinated globally.
- The execution time line is decided by hyperepoch and epoch, which acts very much like simulation time! All runnables are registered in periodical epochs!

## Determinism

First we suppose that there is only one hyperepoch in SOC(reasonable, considering that we use all compute CPU/GPU). First of all the schedule is flatten: *The compiler currently supports two heuristics for flattening the graph into a schedule.*. My understanding is that the scheduling is linear. Note that this does not necessarily mean that the execution of runnables is also linear. On the contrary, since one hyperepoch can have multiple compute engines exculsively, the execution is parallel in nature. I think DriveWorks can achieve deterministic behavior. This is because it's a time budget system:

- Hyperepochs are scheduled using the period of the hyperepoch
- Inside hyperepoch, frames of one same epoch is synchronized using framesync client, which can make sure that frames of the same epoch are executed sequentially
- Inside each epoch, runnables can have dependency and can be executed sequentially.
- Different epochs inside one hyperepoch are scheduled according to static start time inside hyperepoch, but the relative start/end time between different epochs are **NOT** guaranteed. **STM is only deterministic in scheduling, but cannot guarantee the compute output each time, because the real execution time for each runnable is variant**. Different epochs inside one hyperepoch are parallel. What if they are also synchronized? It will not result in deterministic output, the reason is that epoch is not Node, it does not necessarily accept inputs at the start and give output at the end. Epochs inside hyperepoch are not DAGs. The STM master can do is to make sure hyperepochs(compute resources) are used according to pre-defined, static time-based schedule, it's **determinism in compute, not in result**. What if each epoch also represent a functional unit, like a Node, which during this time slot, it accept inputs and give outputs at the end of this epoch? This way, we can use something like *epochsync* to synchronize, not only frames of same epoch, but also all frames of all epochs under the same hyperepoch: 1. Epoch frames are synchronized and determined. 2. Runables inside each epoch are synchronized(sequentially). When the hyperepoch is run, it should have a deterministic result. But it also have disadvantages: it creates stard/end order in different epochs and might introduce waiting. In reality, what is the desired result when one compute entity is taking time more than expected? should other dependent compute goes on with older data and give normal output, or should other compute be blocked by this abnormal compute entity? 

>Epoch Boundaries
>
>All runnables in an epoch must complete before any runnable in the next epoch can begin. This is implemented via an additional, STM generated client called the framesync client. The framesync client waits on leaf node runnables to signal completion, and then sends a signal to root node runnables to begin executing in the next epoch. Given a schedule overrun, the STM runtime can operate in 2 modes: a frameskip mode and a free-running mode.
>
>- Frameskip Mode In this mode, the framesync client will block the start of the next epoch until the next multiple of the epoch length. For example, if the epoch length is 100ms, and the last runnable in an epoch completes at t=350ms, the next epoch will start at t=400ms. If the epoch length is 100ms and the last runnable in an epoch completes at t=90ms, the next epoch will start at t=100ms.
>- No-Frameskip-on-Overrun Mode In this mode, the next epoch will start as soon as all runnables in the previous epoch have finished, if the previous epoch over-ran its scheduled length.

