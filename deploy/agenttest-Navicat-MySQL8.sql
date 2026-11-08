-- AgentTestLab / MySQL 8 / localhost:3306 / agenttest

-- Empty-schema install only. No user data, passwords, DROP, or account changes.

-- Run only against an empty agenttest database. Do not re-run over existing tables.

CREATE DATABASE IF NOT EXISTS `agenttest` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `agenttest`;

SET NAMES utf8mb4;


CREATE TABLE system_parameters (
	`key` VARCHAR(80) NOT NULL, 
	value JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (`key`)
)

;


CREATE TABLE users (
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(200) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
)

;


CREATE TABLE model_configs (
	created_by VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	purpose VARCHAR(30) NOT NULL, 
	config JSON NOT NULL, 
	secret TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;


CREATE TABLE operation_logs (
	user_id VARCHAR(36) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

CREATE INDEX ix_operation_logs_user_id ON operation_logs (user_id);


CREATE TABLE projects (
	owner_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	business_type VARCHAR(50) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;

CREATE INDEX ix_projects_owner_id ON projects (owner_id);


CREATE TABLE agents (
	project_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	config JSON NOT NULL, 
	secret TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
)

;

CREATE INDEX ix_agents_project_id ON agents (project_id);


CREATE TABLE demo_runs (
	project_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	model_snapshot JSON NOT NULL, 
	payload MEDIUMTEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;

CREATE INDEX ix_demo_runs_project_id ON demo_runs (project_id);


CREATE TABLE generation_runs (
	owner_id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36) NOT NULL, 
	model_config_id VARCHAR(36), 
	status VARCHAR(30) NOT NULL, 
	request_data JSON NOT NULL, 
	model_snapshot JSON NOT NULL, 
	result JSON, 
	raw_response MEDIUMTEXT, 
	`usage` JSON NOT NULL, 
	error_code VARCHAR(80), 
	saved_indexes JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(model_config_id) REFERENCES model_configs (id) ON DELETE SET NULL
)

;

CREATE INDEX ix_generation_runs_owner_id ON generation_runs (owner_id);

CREATE INDEX ix_generation_runs_project_id ON generation_runs (project_id);


CREATE TABLE knowledge_bases (
	project_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	config JSON NOT NULL, 
	secrets MEDIUMTEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
)

;

CREATE INDEX ix_knowledge_bases_project_id ON knowledge_bases (project_id);


CREATE TABLE test_suites (
	project_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
)

;

CREATE INDEX ix_test_suites_project_id ON test_suites (project_id);


CREATE TABLE agent_versions (
	agent_id VARCHAR(36) NOT NULL, 
	version INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	secret TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (agent_id, version), 
	FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE CASCADE
)

;

CREATE INDEX ix_agent_versions_agent_id ON agent_versions (agent_id);


CREATE TABLE rag_datasets (
	kb_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	config JSON NOT NULL, 
	payload MEDIUMTEXT NOT NULL, 
	error_code VARCHAR(100), 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kb_id) REFERENCES knowledge_bases (id)
)

;

CREATE INDEX ix_rag_datasets_kb_id ON rag_datasets (kb_id);


CREATE TABLE rag_documents (
	kb_id VARCHAR(36) NOT NULL, 
	name VARCHAR(240) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	source MEDIUMTEXT NOT NULL, 
	error_code VARCHAR(100), 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kb_id) REFERENCES knowledge_bases (id)
)

;

CREATE INDEX ix_rag_documents_kb_id ON rag_documents (kb_id);


CREATE TABLE rag_evaluations (
	kb_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	config JSON NOT NULL, 
	payload MEDIUMTEXT NOT NULL, 
	error_code VARCHAR(100), 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kb_id) REFERENCES knowledge_bases (id)
)

;

CREATE INDEX ix_rag_evaluations_kb_id ON rag_evaluations (kb_id);


CREATE TABLE test_cases (
	suite_id VARCHAR(36) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	test_type VARCHAR(30) NOT NULL, 
	scenario TEXT NOT NULL, 
	preconditions TEXT NOT NULL, 
	user_input MEDIUMTEXT NOT NULL, 
	history JSON NOT NULL, 
	expected_behavior TEXT NOT NULL, 
	expected_result TEXT NOT NULL, 
	rules JSON NOT NULL, 
	priority VARCHAR(5) NOT NULL, 
	tags JSON NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	generation_run_id VARCHAR(36), 
	revision INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(suite_id) REFERENCES test_suites (id), 
	FOREIGN KEY(generation_run_id) REFERENCES generation_runs (id)
)

;

CREATE INDEX ix_test_cases_test_type ON test_cases (test_type);

CREATE INDEX ix_test_cases_suite_id ON test_cases (suite_id);


CREATE TABLE test_suite_versions (
	suite_id VARCHAR(36) NOT NULL, 
	revision INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (suite_id, revision), 
	FOREIGN KEY(suite_id) REFERENCES test_suites (id)
)

;

CREATE INDEX ix_test_suite_versions_suite_id ON test_suite_versions (suite_id);


CREATE TABLE test_tasks (
	project_id VARCHAR(36) NOT NULL, 
	agent_id VARCHAR(36) NOT NULL, 
	suite_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	config JSON NOT NULL, 
	snapshot JSON NOT NULL, 
	secrets MEDIUMTEXT NOT NULL, 
	error_code VARCHAR(100), 
	started_at VARCHAR(40), 
	finished_at VARCHAR(40), 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(agent_id) REFERENCES agents (id), 
	FOREIGN KEY(suite_id) REFERENCES test_suites (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;

CREATE INDEX ix_test_tasks_status ON test_tasks (status);

CREATE INDEX ix_test_tasks_agent_id ON test_tasks (agent_id);

CREATE INDEX ix_test_tasks_project_id ON test_tasks (project_id);


CREATE TABLE rag_chunks (
	kb_id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	content TEXT NOT NULL, 
	page_number INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	meta JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kb_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(document_id) REFERENCES rag_documents (id)
)

;

CREATE INDEX ix_rag_chunks_document_id ON rag_chunks (document_id);

CREATE INDEX ix_rag_chunks_kb_id ON rag_chunks (kb_id);

CREATE INDEX ix_rag_chunks_content_hash ON rag_chunks (content_hash);


CREATE TABLE rag_issues (
	kb_id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36), 
	kind VARCHAR(40) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	detail JSON NOT NULL, 
	confirmation VARCHAR(30) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kb_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(document_id) REFERENCES rag_documents (id)
)

;

CREATE INDEX ix_rag_issues_kb_id ON rag_issues (kb_id);


CREATE TABLE regression_records (
	project_id VARCHAR(36) NOT NULL, 
	baseline_id VARCHAR(36) NOT NULL, 
	candidate_id VARCHAR(36) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(baseline_id) REFERENCES test_tasks (id), 
	FOREIGN KEY(candidate_id) REFERENCES test_tasks (id)
)

;

CREATE INDEX ix_regression_records_project_id ON regression_records (project_id);


CREATE TABLE reports (
	task_id VARCHAR(36) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES test_tasks (id)
)

;

CREATE INDEX ix_reports_task_id ON reports (task_id);


CREATE TABLE test_results (
	task_id VARCHAR(36) NOT NULL, 
	case_key VARCHAR(36) NOT NULL, 
	case_name VARCHAR(160) NOT NULL, 
	test_type VARCHAR(30) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	duration_ms FLOAT, 
	attempts INTEGER NOT NULL, 
	payload MEDIUMTEXT NOT NULL, 
	error_code VARCHAR(100), 
	`usage` JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id, case_key), 
	FOREIGN KEY(task_id) REFERENCES test_tasks (id)
)

;

CREATE INDEX ix_test_results_task_id ON test_results (task_id);


CREATE TABLE evaluation_details (
	result_id VARCHAR(36) NOT NULL, 
	evaluator VARCHAR(40) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	score FLOAT, 
	detail JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(result_id) REFERENCES test_results (id)
)

;

CREATE INDEX ix_evaluation_details_result_id ON evaluation_details (result_id);


CREATE TABLE security_findings (
	task_id VARCHAR(36) NOT NULL, 
	result_id VARCHAR(36) NOT NULL, 
	category VARCHAR(60) NOT NULL, 
	risk VARCHAR(20) NOT NULL, 
	violated VARCHAR(20) NOT NULL, 
	detail JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES test_tasks (id), 
	FOREIGN KEY(result_id) REFERENCES test_results (id)
)

;

CREATE INDEX ix_security_findings_task_id ON security_findings (task_id);

CREATE INDEX ix_security_findings_result_id ON security_findings (result_id);


CREATE TABLE trace_events (
	task_id VARCHAR(36) NOT NULL, 
	result_id VARCHAR(36) NOT NULL, 
	parent_event_id VARCHAR(36), 
	event_type VARCHAR(50) NOT NULL, 
	event_name VARCHAR(160) NOT NULL, 
	duration_ms FLOAT, 
	status VARCHAR(30) NOT NULL, 
	payload MEDIUMTEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES test_tasks (id), 
	FOREIGN KEY(result_id) REFERENCES test_results (id)
)

;

CREATE INDEX ix_trace_events_result_id ON trace_events (result_id);

CREATE INDEX ix_trace_events_task_id ON trace_events (task_id);

CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)) ENGINE=InnoDB;

INSERT INTO alembic_version (version_num) VALUES ('0007_delivery');

SELECT DATABASE() AS current_database;

SHOW TABLES;

SELECT version_num FROM alembic_version;
