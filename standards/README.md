# Standards

This directory contains the architectural conventions and coding standards for the AMRIT platform. These are machine-readable YAML definitions that describe the expected patterns, layering rules, and naming conventions across the AMRIT codebase.

## Purpose

The standards serve two functions:

1. **Human reference:** Engineers contributing to AMRIT repositories can consult these files to understand the expected code structure before writing a single line.

2. **Machine consumption:** The `cross-repo` intelligence engine loads annotation and naming patterns to classify components. Dependency-direction validation from `allowed_dependencies` is not implemented.

## Files

| File | Scope | What It Defines |
|---|---|---|
| `spring-boot.yml` | Java backend services | Three-layer architecture (Controller, Service, Repository), REST path conventions, DTO naming, DI patterns, exception handling |
| `angular.yml` | TypeScript frontend apps | Module structure, component naming, HttpClient usage, dependency injection, state management |

## How Standards Are Used

When the `cross-repo` graph engine ingests a repository, it classifies each discovered class using the patterns defined here:

- A Java class annotated with `@RestController` is classified as `controller` (per `spring-boot.yml` layering rules)
- A TypeScript class named `*Service` with constructor-injected `HttpClient` is classified as `service` (per `angular.yml` naming conventions)
- Rules load from `STANDARDS_DIR` (defaults to this directory in a repository checkout); built-in classification remains a fallback if the YAML files are absent.
- A standalone cross-repo Docker build does not include this sibling directory. Mount it read-only and set `STANDARDS_DIR=/standards` in that container.
- Restart the service after changing YAML; parsed rules are cached. Malformed YAML raises an error rather than silently ignoring standards.

## Adding New Standards

To add conventions for a new framework or language:

1. Create a new YAML file in this directory (e.g., `react-native.yml`)
2. Follow the same structure: top-level sections for layering, naming, and conventions
3. Each rule should have a `description`, concrete `patterns`, and `examples`
4. Update this README to include the new file in the table above
