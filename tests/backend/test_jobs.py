import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_job_creation():
    """Test job creation endpoint"""
    response = client.post("/jobs", json={"task": "test_task"})
    assert response.status_code == 201
    assert "job_id" in response.json()

def test_job_claim():
    """Test job claiming"""
    response = client.post("/jobs/123/claim", json={"agent_id": "agent_1"})
    assert response.status_code == 200
    assert "status" in response.json()

def test_job_start():
    """Test job start"""
    response = client.post("/jobs/123/start", json={"agent_id": "agent_1"})
    assert response.status_code == 200
    assert "status" in response.json()