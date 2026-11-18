from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from neo4j import GraphDatabase

from config import get_settings
from core.graph_identity import dependency_type, entity_id
from core.route_normalizer import normalize_route, routes_match


class Neo4jClient:
    """Versioned graph store. Readers only see a completely committed snapshot.

    Vayasya-prefixed labels intentionally do not reuse legacy constraints/nodes.
    Building a snapshot never deletes or mutates the legacy graph.
    """

    def __init__(self) -> None:
        s = get_settings()
        self._driver = GraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password),
            connection_timeout=10,
        )
        self._graph_key = s.graph_namespace
        self._build_timeout = s.graph_build_timeout_seconds
        self._transaction = None
        self._build_id = None

    def close(self) -> None:
        self._driver.close()

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                'CREATE CONSTRAINT vayasya_graph_key IF NOT EXISTS '
                'FOR (s:VayasyaGraphState) REQUIRE s.key IS UNIQUE'
            ).consume()
            for label in ('Repo', 'File', 'Class', 'Endpoint', 'HttpCall', 'Unresolved'):
                session.run(
                    f'CREATE CONSTRAINT vayasya_{label.lower()}_identity IF NOT EXISTS '
                    f'FOR (n:Vayasya{label}) REQUIRE (n.build_id, n.id) IS UNIQUE'
                ).consume()
        # Constraint/connection errors must abort a build, not be swallowed.

    @contextmanager
    def build_snapshot(self):
        if self._transaction is not None:
            raise RuntimeError('A graph snapshot build is already open')
        build_id = str(uuid4())
        with self._driver.session() as session:
            with session.begin_transaction(timeout=self._build_timeout) as tx:
                # Hold one namespace-specific write lock for the whole build.
                # Other builders serialize; readers continue seeing the old snapshot.
                tx.run(
                    'MERGE (s:VayasyaGraphState {key: $graph_key}) '
                    'SET s.lock_version = coalesce(s.lock_version, 0) + 1',
                    graph_key=self._graph_key,
                ).consume()
                self._transaction, self._build_id = tx, build_id
                try:
                    yield build_id
                    tx.run(
                        'MATCH (s:VayasyaGraphState {key: $graph_key}) '
                        'SET s.build_id = $build_id, s.published_at = datetime()',
                        graph_key=self._graph_key, build_id=build_id,
                    ).consume()
                    tx.commit()
                finally:
                    self._transaction, self._build_id = None, None
                # The transaction context rolls back on failure; the active pointer
                # and the previous snapshot remain unchanged.

    def _write(self, query: str, **parameters):
        if self._transaction is None or self._build_id is None:
            raise RuntimeError('Graph writes require build_snapshot()')
        return self._transaction.run(query, build_id=self._build_id, **parameters)

    def _read(self, query: str, **parameters) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            return session.run(
                query, graph_key=self._graph_key, **parameters,
            ).data()

    def upsert_repo(self, name: str) -> None:
        self._write(
            'MERGE (r:VayasyaEntity:VayasyaRepo {build_id: $build_id, id: $name}) '
            'SET r.name = $name', name=name,
        ).consume()

    def upsert_file(self, path: str, repo: str, language: str | None, framework: str | None) -> None:
        self._write(
            '''
            MATCH (r:VayasyaRepo {build_id: $build_id, id: $repo})
            MERGE (f:VayasyaEntity:VayasyaFile {build_id: $build_id, id: $uid})
            SET f.path = $path, f.repo = $repo, f.language = $language, f.framework = $framework
            MERGE (f)-[:BELONGS_TO]->(r)
            ''',
            uid=entity_id(repo, path), path=path, repo=repo,
            language=language or '', framework=framework or '',
        ).consume()

    def upsert_class(self, name: str, kind: str, file_path: str, repo: str) -> None:
        self._write(
            '''
            MATCH (f:VayasyaFile {build_id: $build_id, id: $file_id})
            MERGE (c:VayasyaEntity:VayasyaClass {build_id: $build_id, id: $uid})
            SET c.name = $name, c.kind = $kind, c.repo = $repo
            MERGE (c)-[:DEFINED_IN]->(f)
            ''',
            uid=entity_id(repo, file_path, name), file_id=entity_id(repo, file_path),
            name=name, kind=kind, repo=repo,
        ).consume()

    def upsert_endpoint(
        self, method: str, path: str, handler_class_id: str | None, repo: str,
        request_dto: str | None = None, response_dto: str | None = None,
    ) -> None:
        uid = entity_id(repo, method.upper(), path)
        self._write(
            '''
            MERGE (e:VayasyaEntity:VayasyaEndpoint {build_id: $build_id, id: $uid})
            SET e.method = $method, e.path = $path, e.normalized_path = $norm_path,
                e.repo = $repo, e.request_dto = $request_dto, e.response_dto = $response_dto
            ''',
            uid=uid, method=method.upper(), path=path, norm_path=normalize_route(path),
            repo=repo, request_dto=request_dto or '', response_dto=response_dto or '',
        ).consume()
        if handler_class_id:
            self._write(
                '''
                MATCH (e:VayasyaEndpoint {build_id: $build_id, id: $eid}),
                      (c:VayasyaClass {build_id: $build_id, id: $cid})
                MERGE (c)-[:HANDLES]->(e)
                ''', eid=uid, cid=handler_class_id,
            ).consume()

    def upsert_http_call(self, method: str, path: str, caller_class_id: str | None, repo: str) -> None:
        uid = entity_id(repo, method.upper(), path)
        self._write(
            '''
            MERGE (h:VayasyaEntity:VayasyaHttpCall {build_id: $build_id, id: $uid})
            SET h.method = $method, h.path = $path,
                h.normalized_path = $norm_path, h.repo = $repo
            ''',
            uid=uid, method=method.upper(), path=path, norm_path=normalize_route(path), repo=repo,
        ).consume()
        if caller_class_id:
            self._write(
                '''
                MATCH (h:VayasyaHttpCall {build_id: $build_id, id: $hid}),
                      (c:VayasyaClass {build_id: $build_id, id: $cid})
                MERGE (c)-[:MAKES]->(h)
                ''', hid=uid, cid=caller_class_id,
            ).consume()

    def link_dependencies(self, class_id: str, dep_names: list[str], repo: str) -> None:
        dependencies = [
            {
                'name': name, 'uid': entity_id(class_id, name),
                'type': dependency_type(name),
                'context': f'Injected into {class_id}; no class named {name} in repository {repo}',
            }
            for name in sorted(set(dep_names))
        ]
        self._write(
            '''
            MATCH (src:VayasyaClass {build_id: $build_id, id: $src_id})
            UNWIND $dependencies AS dependency
            OPTIONAL MATCH (dep:VayasyaClass {
                build_id: $build_id, name: dependency.name, repo: $repo
            })
            WITH src, dependency, collect(dep) AS resolved
            FOREACH (target IN resolved | MERGE (src)-[:DEPENDS_ON]->(target))
            FOREACH (missing IN CASE WHEN size(resolved) = 0 THEN [1] ELSE [] END |
                MERGE (u:VayasyaEntity:VayasyaUnresolved {
                    build_id: $build_id, id: dependency.uid
                })
                SET u.name = dependency.name, u.dep_type = dependency.type,
                    u.context = dependency.context
                MERGE (src)-[:DEPENDS_ON_EXTERNAL]->(u)
            )
            ''',
            src_id=class_id, repo=repo, dependencies=dependencies,
        ).consume()

    def link_http_calls_to_endpoints(self) -> int:
        calls = self._write(
            'MATCH (h:VayasyaHttpCall {build_id: $build_id}) '
            'RETURN h.id AS id, h.method AS method, h.path AS path ORDER BY h.id',
        ).data()
        endpoints = self._write(
            'MATCH (e:VayasyaEndpoint {build_id: $build_id}) '
            'RETURN e.id AS id, e.method AS method, e.path AS path ORDER BY e.id',
        ).data()
        links = []
        for call in calls:
            for endpoint in endpoints:
                if call['method'] != endpoint['method']:
                    continue
                matched, quality = routes_match(call['path'], endpoint['path'])
                if matched:
                    links.append({
                        'caller': call['id'], 'endpoint': endpoint['id'], 'quality': quality,
                        'confidence': {'exact': 1.0, 'template': 0.85, 'prefix': 0.6}[quality],
                    })
        self._write(
            '''
            UNWIND $links AS link
            MATCH (h:VayasyaHttpCall {build_id: $build_id, id: link.caller}),
                  (e:VayasyaEndpoint {build_id: $build_id, id: link.endpoint})
            MERGE (h)-[r:RESOLVES_TO]->(e)
            SET r.match_quality = link.quality, r.confidence = link.confidence
            ''', links=links,
        ).consume()
        return len(links)

    def query_all_endpoints(self, repo_name: str | None = None) -> list[dict[str, Any]]:
        return self._read(
            '''
            MATCH (s:VayasyaGraphState {key: $graph_key})
            MATCH (e:VayasyaEndpoint {build_id: s.build_id})
            WHERE $repo_name = '' OR e.repo = $repo_name
            OPTIONAL MATCH (e)<-[:HANDLES]-(handler:VayasyaClass)-[:DEFINED_IN]->(f:VayasyaFile)
            OPTIONAL MATCH (caller:VayasyaClass)-[:MAKES]->(:VayasyaHttpCall)-[:RESOLVES_TO]->(e)
            OPTIONAL MATCH (caller)-[:DEFINED_IN]->(cf:VayasyaFile)
            RETURN e.method AS method, e.path AS path, e.repo AS endpoint_repo,
                collect(DISTINCT {
                    name: handler.name, kind: handler.kind, file: f.path, repo: handler.repo
                }) AS handlers,
                collect(DISTINCT {
                    caller: caller.name, file: cf.path, repo: caller.repo
                }) AS frontend_callers
            ORDER BY endpoint_repo, method, path
            ''', repo_name=repo_name or '',
        )

    def query_trace(self, feature: str) -> list[dict[str, Any]]:
        return self._read(
            '''
            MATCH (s:VayasyaGraphState {key: $graph_key})
            MATCH (e:VayasyaEndpoint {build_id: s.build_id})
            WHERE toLower(e.path) CONTAINS toLower($feature)
            OPTIONAL MATCH chain=(e)<-[:HANDLES]-(c:VayasyaClass)-[:DEPENDS_ON*0..5]->(dep:VayasyaClass)
            OPTIONAL MATCH (dep)-[:DEPENDS_ON_EXTERNAL]->(u:VayasyaUnresolved)
            OPTIONAL MATCH (caller:VayasyaClass)-[:MAKES]->(h:VayasyaHttpCall)-[:RESOLVES_TO]->(e)
            OPTIONAL MATCH (caller)-[:DEFINED_IN]->(cf:VayasyaFile)
            OPTIONAL MATCH (c)-[:DEFINED_IN]->(bf:VayasyaFile)
            RETURN e.method AS method, e.path AS path,
                c.name AS handler_class, c.kind AS handler_kind,
                bf.path AS backend_file, e.repo AS backend_repo,
                [n IN nodes(chain) WHERE n:VayasyaClass | n.name] AS service_chain,
                collect(DISTINCT {
                    caller: caller.name, file: cf.path, repo: caller.repo, path: h.path
                }) AS frontend_callers,
                collect(DISTINCT {
                    name: u.name, type: u.dep_type, context: u.context
                }) AS unresolved_hops
            ORDER BY backend_repo, method, path, handler_class, service_chain
            ''', feature=feature,
        )

    def query_dependencies(self, class_name: str, repo_name: str | None = None) -> list[dict[str, Any]]:
        return self._read(
            '''
            MATCH (s:VayasyaGraphState {key: $graph_key})
            MATCH (c:VayasyaClass {build_id: s.build_id, name: $class_name})
            WHERE $repo_name = '' OR c.repo = $repo_name
            OPTIONAL MATCH (c)-[:DEPENDS_ON*1..5]->(dep:VayasyaClass)
            RETURN c.name AS source, collect(DISTINCT dep.name) AS dependencies, c.repo AS repo
            ORDER BY repo, source
            ''', class_name=class_name, repo_name=repo_name or '',
        )

    def stats(self) -> dict[str, int]:
        rows = self._read(
            '''
            MATCH (s:VayasyaGraphState {key: $graph_key})
            OPTIONAL MATCH (n:VayasyaEntity {build_id: s.build_id})
            WITH s,
                sum(CASE WHEN n:VayasyaRepo THEN 1 ELSE 0 END) AS repos,
                sum(CASE WHEN n:VayasyaFile THEN 1 ELSE 0 END) AS files,
                sum(CASE WHEN n:VayasyaClass THEN 1 ELSE 0 END) AS classes,
                sum(CASE WHEN n:VayasyaEndpoint THEN 1 ELSE 0 END) AS endpoints,
                sum(CASE WHEN n:VayasyaHttpCall THEN 1 ELSE 0 END) AS httpcalls
            OPTIONAL MATCH (:VayasyaHttpCall {build_id: s.build_id})-[r:RESOLVES_TO]->()
            RETURN repos, files, classes, endpoints, httpcalls, count(r) AS resolved_links
            '''
        )
        return rows[0] if rows else dict.fromkeys(
            ('repos', 'files', 'classes', 'endpoints', 'httpcalls', 'resolved_links'), 0,
        )
