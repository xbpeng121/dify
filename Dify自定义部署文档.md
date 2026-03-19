## Dify 自定义部署文档

### 选型说明

基于Dify官方1.11.4分支上，修复和改进其中部分能力后，独立编译运行。

fork并修改的分支维护于https://github.com/xbpeng121/dify

### 变化内容

1. 修改所有files/upload 接口，默认通过此接口上传的文件为临时文件，将会在一定时间内被删除，有效时间可在.env中设置(CLEAN_UPLOAD_TEMPORARY_FILE_DAY_SETTING)。
2. [知识库]修复某些情况下，dify Indexing时对文件内的图片另存逻辑有bug，导致在删除文件时无法同步删除另存的图片。
3. workflows/run接口，新增可直接接受base64文件的能力。
4. 工作流开放接口中新增 /workflows/output 接口，允许第三方查询工作流的输出参数。
5. 开放接口中新增 /info 接口，新增app_mode字段输出。
6. 修改docker-compose文件，默认引用自编译镜像



### docker部署

1. 下载源代码到本地，切换到指定分支

   ```shell
   git clone https://github.com/xbpeng121/dify.git
   git checkout release/e-1.11.4-sibat
   ```

2. 编译api镜像

   ```shell
   cd api
   docker build --platform linux/amd64 -t sibat-dify-api:1.11.4 .
   ```

3. 编译web镜像

   ```shell
   cd web
   docker build --platform linux/amd64 -t sibat-dify-web:1.11.4 .
   ```

4. 编辑配置文件并启动

   ```shell
   cd docker
   cp .env.example .env
   docker compose up -d
   ```

5. 若服务环境不方便拉取和编译，可以拷贝代码和镜像文件

   ```shell
   # 备份镜像文件
   docker save sibat-dify-api:0.15.6 > sibat-dify-api.tar
   docker save sibat-dify-web:0.15.6 > sibat-dify-web.tar
   
   # 导入镜像文件
   docker load -i sibat-dify-api.tar
   docker load -i sibat-dify-web.tar
   ```



### K8s部署（详见k8s目录下README文档）

1. 下载源代码到本地，切换到指定分支

   ```shell
   git clone https://github.com/xbpeng121/dify.git
   git checkout release/e-1.11.4-sibat
   ```

2. 进入k8s目录，并赋予脚本执行权限   

   ```shell
   cd k8s
   # 赋予执行权限
   chmod +x harbor_setup.sh
   chmod +x deploy.sh
   ```

3. 初始化harbor库，并上传所有需要的镜像

   ```shell   
   # 根据脚本指引初始化harbor库、并上传镜像文件
   sh harbor_setup.sh
   ```

4. 根据需要配置环境变量

   ```shell   
   # 编辑环境变量文件
   vim configmap.yaml
   vim secrets.yaml
   ```

5. 使用部署脚本，完成部署、查看、删除

   ```shell   
   # 部署所有资源
   sh deploy.sh apply
   
   # 查看状态
   sh deploy.sh status
   
   # 删除所有资源
   sh deploy.sh delete
   ```



### 环境变量

运行前，执行`cp .env.example .env`命令，然后根据需要配置环境变量，以下列举了不可忽视的环境变量，特别是初次部署时需要按需修改

#### SECRET_KEY

一个用于安全地签名会话 cookie 并在数据库上加密敏感信息的密钥。初次启动需要设置改变量。可以运行 `openssl rand -base64 42` 生成一个强密钥。

#### DEPLOY_ENV

部署环境。

- PRODUCTION（默认）

  生产环境。

- TESTING

  测试环境，前端页面会有明显颜色标识，该环境为测试环境。

#### LOG_LEVEL

日志输出等级，默认为 INFO。生产建议设置为 ERROR。

#### CHECK_UPDATE_URL

是否开启检查版本策略，若设置为 false，则不调用 `https://updates.dify.ai` 进行版本检查。

#### TEXT_GENERATION_TIMEOUT_MS

前端客户端配置，用于限制文本生成请求的超时时间，防止因某些进程运行超时而导致整体服务不可用。默认 60000ms（60秒）

#### APP_MAX_ACTIVE_REQUESTS

每个应用最大活动请求数量，默认为0，表示不限制

#### APP_MAX_EXECUTION_TIME

应用允许的最大执行时间，以秒为单位，默认为1200秒（20分钟）

#### SERVER_WORKER_AMOUNT

API 服务 Server worker 数量，建议公式：`cpu 核心数 x 2 + 1`

#### SERVER_WORKER_CONNECTIONS

API 服务每个工作进程的最大连接数

#### CELERY_WORKER_AMOUNT

Worker服务 Celery worker数量

#### CELERY_AUTO_SCALE

Worker服务 是否启用自动扩缩容

#### CELERY_MAX_WORKERS

#### CELERY_MIN_WORKERS

Worker服务 启用自动扩缩容后，最大worker数量和最小worker数量



### 支持较高并发的参数配置

假设在一个4核处理器上，目标为100qps，

```shell
 ## API服务配置
 # 如果I/O密集（有大量请求）
 SERVER_WORKER_AMOUNT=9 # 4*2+1
 SERVER_WORKER_CLASS=gevent
 SERVER_WORKER_CONNECTIONS=20
 # 如果CPU密集，可以变异步为同步
 SERVER_WORKER_AMOUNT=9
 SERVER_WORKER_CLASS=sync
 
 ## Worker服务配置  (目前业务对Celery Worker依赖较少，基本不需要增加workers)
 #启用自动扩缩容
 CELERY_AUTO_SCALE=true
 CELERY_MAX_WORKERS=20     # 最大worker数量
 CELERY_MIN_WORKERS=5      # 最小worker数量
 CELERY_WORKER_CLASS=gevent # 使用异步模式

```

查看API服务配置是否生效：

```shell
ps -ef |grep gunicorn 
# 查看进程会出现类似如下信息，查看--workers 参数和进程数量是否与配置一致
root  2 1  /python /gunicorn --workers 3 --worker-class gevent --worker-connections 20 app:app
root  3 2  /python /gunicorn --workers 3 --worker-class gevent --worker-connections 20 app:app
root  4 2  /python /gunicorn --workers 3 --worker-class gevent --worker-connections 20 app:app
root  5 2  /python /gunicorn --workers 3 --worker-class gevent --worker-connections 20 app:app
```

Gunicorn 的工作进程管理：

- Gunicorn 是一个 Python WSGI HTTP 服务器

- 使用 --workers 参数来控制工作进程数量

- 每个工作进程都是一个独立的 Python 进程

- 工作进程由 Gunicorn 的主进程（master process）管理

工作方式如下：

```markdown
Gunicorn Master Process
    |
    +-- Worker Process 1 (处理请求)
    +-- Worker Process 2 (处理请求)
    +-- Worker Process N (处理请求)
```



### 文件上传方式性能对比

- upload用例：采用默认upload接口上传后，获取文件id，再调用workflow_run接口

- base64用例：将文件转换为base64后，直接调用workflow_run接口

  使用相同图片，图片大小2M，每种用例执行50次，统计性能数据

  base64用例：

  ```shell
  总测试次数：50次
  成功次数：50次
  失败次数：0次
  平均耗时：3.06秒
  中位数耗时：3.07秒
  最小耗时：2.28秒
  最大耗时：4.22秒
  标准差：0.31秒
  
  耗时分布：
  0% 的请求耗时小于 2.76秒
  10% 的请求耗时小于 2.81秒
  20% 的请求耗时小于 2.86秒
  30% 的请求耗时小于 2.95秒
  40% 的请求耗时小于 3.07秒
  50% 的请求耗时小于 3.08秒
  60% 的请求耗时小于 3.17秒
  70% 的请求耗时小于 3.26秒
  80% 的请求耗时小于 3.38秒
  ```

  upload用例：

  ```shell
  测试结果统计:
  总测试次数: 50
  成功次数: 50
  失败次数: 0
  
  文件上传统计:
    平均耗时: 0.38秒
    中位数耗时: 0.37秒
    最小耗时: 0.19秒
    最大耗时: 0.89秒
    标准差: 0.18秒
  
  文件上传耗时分布:
    0% 的请求耗时小于 0.19秒
    10% 的请求耗时小于 0.21秒
    20% 的请求耗时小于 0.25秒
    30% 的请求耗时小于 0.27秒
    40% 的请求耗时小于 0.31秒
    50% 的请求耗时小于 0.37秒
    60% 的请求耗时小于 0.40秒
    70% 的请求耗时小于 0.41秒
    80% 的请求耗时小于 0.51秒
    90% 的请求耗时小于 0.61秒
    100% 的请求耗时小于 0.89秒
  
  工作流执行统计:
    平均耗时: 2.97秒
    中位数耗时: 2.96秒
    最小耗时: 2.27秒
    最大耗时: 3.43秒
    标准差: 0.28秒
  
  工作流执行耗时分布:
    0% 的请求耗时小于 2.27秒
    10% 的请求耗时小于 2.65秒
    20% 的请求耗时小于 2.77秒
    30% 的请求耗时小于 2.84秒
    40% 的请求耗时小于 2.87秒
    50% 的请求耗时小于 2.97秒
    60% 的请求耗时小于 3.06秒
    70% 的请求耗时小于 3.18秒
    80% 的请求耗时小于 3.25秒
    90% 的请求耗时小于 3.34秒
    100% 的请求耗时小于 3.43秒
  
  总耗时统计:
    平均耗时: 3.36秒
    中位数耗时: 3.34秒
    最小耗时: 2.46秒
    最大耗时: 4.24秒
    标准差: 0.35秒
  
  总耗时耗时分布:
    0% 的请求耗时小于 2.46秒
    10% 的请求耗时小于 2.99秒
    20% 的请求耗时小于 3.09秒
    30% 的请求耗时小于 3.17秒
    40% 的请求耗时小于 3.28秒
    50% 的请求耗时小于 3.36秒
    60% 的请求耗时小于 3.45秒
    70% 的请求耗时小于 3.56秒
    80% 的请求耗时小于 3.67秒
    90% 的请求耗时小于 3.77秒
    100% 的请求耗时小于 4.24秒
  ```

  由结果可得，整体耗时差别不大，base64无特别明显的优势
