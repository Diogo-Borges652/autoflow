# Arquitetura e decisões

Fluxo: CLI → leitor CSV/XLSX → validação/normalização → deduplicação → consolidação → exportadores. `domain.py` concentra regras sem I/O; adaptadores não decidem políticas monetárias. Não foi adicionado pandas porque o contrato tem sete colunas e a biblioteca padrão cobre o processamento.

`Decimal` conserva centavos, com valores serializados como strings em JSON/XLSX para impedir perda por conversão binária. Tipo receita/despesa define o sinal. Primeira linha válida por ID prevalece e conflitos ficam em relatório; não existe fusão silenciosa de registros.

O processo não modifica a entrada. Calcula SHA-256 antes e após a leitura para detectar mudanças observadas durante o processamento. Isso auxilia rastreabilidade, não autentica a origem nem elimina toda corrida possível com escritores externos. Para consistência, processe uma cópia estável.

A saída é montada em diretório temporário no mesmo filesystem. Um lock exclusivo coordena processos AutoFlow que disputem o mesmo destino; rename disponibiliza a pasta pronta. Destinos existentes são recusados. Não há garantia contra processos externos que ignorem o lock nem persistência garantida após queda de energia (não há fsync).

As entradas não são executadas. XLSX é lido sem links externos e com fórmulas preservadas para detecção/rejeição. defusedxml protege parsers XML usados pelo openpyxl; ZIP, linhas e tamanho são limitados. Exportadores neutralizam fórmulas e escapam HTML; relatório tem CSP e não usa JavaScript. Logs contêm apenas contagens. Categoria pode aparecer no relatório, portanto saída não é anonimizada.

O HTML é deliberadamente um artefato local, portátil e responsivo, com tipografia de sistema, tabelas semânticas, contraste e ausência de recursos remotos. Não requer hosting, conta, API ou biblioteca de gráficos.

Referências técnicas: [CSV da biblioteca padrão](https://docs.python.org/3/library/csv.html), [Decimal](https://docs.python.org/3/library/decimal.html), [openpyxl e segurança XML](https://openpyxl.readthedocs.io/en/stable/).
