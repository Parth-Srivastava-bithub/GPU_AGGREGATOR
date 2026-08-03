1. GPU Model - Done
7. Avaialibility - Done
6. hourly price - Done
2. VRam - Done
8. Current balance - Done
3. Ram (Incremental) - Done
4. Limit count how can we book - Done
5. 8vCpu or General nvCpu what is n here - Done

---

```
 & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
   --remote-debugging-port=9222 `
   --user-data-dir="C:\Users\user\Documents\GPU_AGGREGATE\chrome_cdp_profile"
```

Current output
![alt text](image.png)


Haan bhai, ab seedha **MVP endpoint table** de raha hoon. Yehi kaafi hai, baaki future ka circus baad me. 😌

## Shared catalog endpoints

| Method | Endpoint                                  | Use                                                      |
| ------ | ----------------------------------------- | -------------------------------------------------------- |
| GET    | `/providers`                              | Saare providers list karne ke liye                       |
| GET    | `/gpus`                                   | Sab providers ke GPUs dekhne ke liye                     |
| GET    | `/gpus/{provider}`                        | Ek provider ke GPUs dekhne ke liye                       |
| GET    | `/gpu`                                    | Exact GPU dhoondhne ke liye `provider + name + specs` se |
| GET    | `/runpod/datacenters`                     | RunPod datacenters list karne ke liye                    |
| GET    | `/runpod/datacenter/{datacenter_id}`      | Ek datacenter ka full doc dekhne ke liye                 |
| GET    | `/runpod/datacenter/{datacenter_id}/gpus` | Us datacenter me available GPUs dekhne ke liye           |

---

## Volumes

| Method | Endpoint                      | Use                                |
| ------ | ----------------------------- | ---------------------------------- |
| POST   | `/runpod/volumes`             | Naya network volume banane ke liye |
| GET    | `/runpod/volumes`             | Sab volumes list karne ke liye     |
| GET    | `/runpod/volumes/{volume_id}` | Ek volume detail dekhne ke liye    |
| DELETE | `/runpod/volumes/{volume_id}` | Volume delete karne ke liye        |

---

## Pods

| Method | Endpoint                          | Use                                    |
| ------ | --------------------------------- | -------------------------------------- |
| POST   | `/runpod/pods`                    | Naya pod create karne ke liye          |
| GET    | `/runpod/pods`                    | Sab pods list karne ke liye            |
| GET    | `/runpod/pods/{pod_id}`           | Ek pod ka status/detail dekhne ke liye |
| POST   | `/runpod/pods/{pod_id}/start`     | Pod start karne ke liye                |
| POST   | `/runpod/pods/{pod_id}/stop`      | Pod stop karne ke liye                 |
| POST   | `/runpod/pods/{pod_id}/resume`    | Stopped pod resume karne ke liye       |
| POST   | `/runpod/pods/{pod_id}/terminate` | Pod kill/terminate karne ke liye       |

---

## Serverless

| Method | Endpoint                          | Use                                           |
| ------ | --------------------------------- | --------------------------------------------- |
| POST   | `/runpod/endpoints`               | Naya serverless endpoint create karne ke liye |
| GET    | `/runpod/endpoints`               | Sab serverless endpoints list karne ke liye   |
| GET    | `/runpod/endpoints/{endpoint_id}` | Ek endpoint ka detail dekhne ke liye          |
| PATCH  | `/runpod/endpoints/{endpoint_id}` | Endpoint update/scale karne ke liye           |
| DELETE | `/runpod/endpoints/{endpoint_id}` | Serverless endpoint delete karne ke liye      |

---

## Agent helper endpoints

| Method | Endpoint                         | Use                                             |
| ------ | -------------------------------- | ----------------------------------------------- |
| POST   | `/build/runpod-pod-payload`      | Pod create payload auto banane ke liye          |
| POST   | `/build/runpod-volume-payload`   | Volume create payload auto banane ke liye       |
| POST   | `/build/runpod-endpoint-payload` | Serverless endpoint payload auto banane ke liye |

---

## MVP me bas ye 3 domains enough hain

| Domain     | Kaam                       |
| ---------- | -------------------------- |
| Volumes    | storage create/list/delete |
| Pods       | machine create/manage      |
| Serverless | endpoint create/manage     |

Bas itna. Baaki GitHub deploy, flash deploy, secret store, template wizard ye sab next season ka drama hai.
