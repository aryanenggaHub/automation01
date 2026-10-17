# Splunk Automation

A CLI tool that rebuilds, from Splunk logs, the end-to-end call sequence across Layers that is triggered by an Input API, and writes it to Excel.

## Layers

**Layer**:
One tier in the request path whose calls are logged in Splunk: Gateway, Microservice, or Downstream Integration.
_Avoid_: Tier, hop

**Gateway**:
The Layer where an external request first enters, identified by its Gateway API Endpoint.
_Avoid_: API gateway server, edge

**Microservice**:
The Layer that receives calls routed by the Gateway and calls Downstream Integrations.
_Avoid_: MS, backend

**Downstream Integration**:
A dependency called by a Microservice, either over an API (**Downstream API**) or through a message queue (**Downstream MQ**).
_Avoid_: Backend system, third party

## Analysis

**Input API**:
The single API endpoint, from any Layer, that the user supplies to start an analysis.
_Avoid_: Seed API, source API

**Session**:
One end-to-end request, created when a call enters the Gateway and identified by a Session ID shared by every Layer it touches. One Session yields one API Sequence.
_Avoid_: User session, login session, trace (unless meaning exactly this)

**Session Query**:
The first configured Splunk query, which finds the Session ID(s) in which the Input API appears.

**Sequence Query**:
The second configured Splunk query, which lists every Layer call within one Session in timestamp order.

**API Sequence**:
The timestamp-ordered list of calls across all Layers that belong to one Session.
_Avoid_: Call chain, flow, trace

**Ambiguous**:
A mark on calls within one API Sequence whose relative order cannot be trusted, because they happened close enough in time that they may have run in parallel.
_Avoid_: Conflict, error, duplicate
