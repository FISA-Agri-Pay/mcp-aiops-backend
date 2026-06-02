# PostgreSQL Init Scripts

이 디렉터리는 로컬 PostgreSQL 컨테이너가 최초 실행될 때 적용할 SQL을 두는 위치입니다.

실제 schema SQL과 seed SQL은 내부 공유용이며 Git에 올리지 않습니다.

```text
infra/docker/postgres/init/001_init_schema.sql
infra/docker/postgres/init/002_seed_dev_data.sql
```

공개 가능한 예시는 `*.example.sql` 형식으로만 추가합니다.
