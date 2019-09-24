# Polkascan PRE Harvester
Polkascan PRE Harvester Python Application

## 使用docker开发

### 运行mysql
docker-compose up -d mysql

### 连上mysql
- 方法1：进入容器  
```
  docker-compose exec mysql sh
  mysql -uroot -proot
```

- 方法2：外部客户端  
```
  database:polkascan
  port:33061
  user:root
  password:root
```

### 运行harvester
```
docker-compose up
```

### 增加version，并migrate
1. 进入harvester-api容器中
```
  docker-compose exec harvester-api sh
```

2. 在harvester-api容器中
```
  alembic revision  -m "create data_transfer table"
  alembic upgrade head
```

## Description
The Polkascan PRE Harvester Application transforms a Substrate node's raw data into relational data for various classes of objects, such as: blocks, runtime metadata entities, extrinsics, events and various runtime data entities, such as: timestamps, accounts and balances.

## License
https://github.com/polkascan/polkascan-pre-harvester/blob/master/LICENSE
