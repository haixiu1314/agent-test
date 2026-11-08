CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_foundation

CREATE TABLE users (
    id VARCHAR(36) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    username VARCHAR(50) NOT NULL, 
    password_hash VARCHAR(200) NOT NULL, 
    `role` VARCHAR(20) NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (username)
);

CREATE TABLE projects (
    id VARCHAR(36) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    owner_id VARCHAR(36) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description TEXT NOT NULL, 
    business_type VARCHAR(50) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE INDEX ix_projects_owner_id ON projects (owner_id);

CREATE TABLE agents (
    id VARCHAR(36) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    project_id VARCHAR(36) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    kind VARCHAR(20) NOT NULL, 
    config JSON NOT NULL, 
    secret TEXT NOT NULL, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_agents_project_id ON agents (project_id);

CREATE TABLE agent_versions (
    id VARCHAR(36) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    agent_id VARCHAR(36) NOT NULL, 
    version INTEGER NOT NULL, 
    snapshot JSON NOT NULL, 
    secret TEXT NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (agent_id, version), 
    FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE CASCADE
);

CREATE INDEX ix_agent_versions_agent_id ON agent_versions (agent_id);

CREATE TABLE operation_logs (
    id VARCHAR(36) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    action VARCHAR(80) NOT NULL, 
    resource_id VARCHAR(36) NOT NULL, 
    request_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_operation_logs_user_id ON operation_logs (user_id);

INSERT INTO alembic_version (version_num) VALUES ('0001_foundation');

