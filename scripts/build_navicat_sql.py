"""生成可在 Navicat 的 3306 连接执行的无凭据建库文件。"""
from pathlib import Path
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects.mysql import dialect
from app.models.entities import Base

root = Path(__file__).resolve().parents[1]
statements = [
    '-- AgentTestLab / MySQL 8 / localhost:3306 / agenttest',
    '-- Empty-schema install only. No user data, passwords, DROP, or account changes.',
    '-- Run only against an empty agenttest database. Do not re-run over existing tables.',
    'CREATE DATABASE IF NOT EXISTS `agenttest` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;',
    'USE `agenttest`;',
    'SET NAMES utf8mb4;',
]
for table in Base.metadata.sorted_tables:
    statements.append(str(CreateTable(table).compile(dialect=dialect())) + ';')
    for index in table.indexes:
        statements.append(str(CreateIndex(index).compile(dialect=dialect())) + ';')
statements += [
    'CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)) ENGINE=InnoDB;',
    "INSERT INTO alembic_version (version_num) VALUES ('0007_delivery');",
    'SELECT DATABASE() AS current_database;',
    'SHOW TABLES;',
    'SELECT version_num FROM alembic_version;',
]
output = root / 'deploy/agenttest-Navicat-MySQL8.sql'
output.write_text('\n\n'.join(statements) + '\n', encoding='utf-8')
print('Generated deploy/agenttest-Navicat-MySQL8.sql (25 business tables + migration table).')
