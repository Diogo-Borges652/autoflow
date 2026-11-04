# Validação — 04/11/2026

Execução local em Linux, Python 3.14.8. Os resultados abaixo pertencem a esta versão; não representam homologação em outros sistemas operacionais.

| Verificação | Resultado observado |
|---|---|
| `python -m unittest discover -s tests -v` | 36 testes aprovados, incluindo CLI por subprocesso e leitura/escrita XLSX |
| `ruff check autoflow tests scripts` | Aprovado |
| `ruff format --check autoflow tests scripts` | 10 arquivos formatados |
| `python -m pip check` | Nenhuma dependência incompatível |
| `python -m build --no-isolation` | Wheel e sdist gerados |
| Instalação do wheel com `pip --no-deps --no-index` | Concluída; entrypoint executado com a fixture fictícia |
| CSV e XLSX de exemplo | Ambos: 9 linhas, 5 aceitas, 2 duplicadas, 2 inválidas; saldo 3404.60 |
| `pip_audit -r requirements.txt` | Nenhuma vulnerabilidade conhecida encontrada na consulta online |
| Chromium + axe-core | 390, 768 e 1440 px sem overflow de página e sem violações nas regras WCAG 2 A/AA e 2.1 AA executadas |

A primeira revisão de acessibilidade encontrou tabelas roláveis sem foco por teclado. Foram adicionados foco, nome acessível e indicador visual; a nova execução passou. Zero violações automatizadas não equivale a certificação completa de acessibilidade.

As capturas PNG foram obtidas do HTML real exportado, no navegador, usando somente o exemplo fictício. Revisão manual visual da captura desktop realizada. O harness de navegador reutilizou Playwright e axe-core já instalados no workspace; eles não são dependências do produto. A CI não executa esses testes de navegador.

Auditoria de publicação: inspeção do conjunto versionado e varredura de padrões em todos os blobs Git alcançáveis com `scripts/security_audit.py`. Não foi incorporado código de projetos comerciais, bancos, ambientes, logs de operação ou credenciais. A varredura é complementar à revisão, não uma prova absoluta de ausência de segredos.

A matriz de CI inclui Python 3.11 e 3.14. Resultados remotos devem ser consultados na aba Actions; não são inferidos a partir do teste local. Não houve teste com dados de clientes, execução de integração externa ou implantação de serviço.
