# AGENTS.md — Katherine Bot

Este arquivo define as regras obrigatórias para agentes de código, incluindo Jules.

## Autoridade e fluxo

- O mantenedor/auditor define arquitetura, prioridade, escopo e critérios de aceite.
- O agente implementa somente a tarefa recebida e entrega a mudança por pull request.
- Sempre crie uma branch nova a partir da `main` atualizada e abra a PR contra `main`.
- Nunca crie PR empilhada sobre a branch de outra PR. Se uma dependência ainda não foi mesclada, declare o bloqueio no comentário inicial e não implemente sobre ela.
- Uma tarefa gera no máximo uma PR. Não recrie automaticamente uma PR fechada e não duplique trabalho existente.
- O Jules não deve depender de comentários posteriores, threads ou pedidos de alteração na PR. Correções após a abertura serão enviadas como uma nova tarefa explícita pelo mantenedor.

## Escopo

- Não faça melhorias paralelas, refatorações oportunistas ou alterações cosméticas fora da tarefa.
- Não edite `.Jules/palette.md` salvo quando a tarefa pedir explicitamente.
- Preserve contratos públicos e dados persistidos; qualquer quebra exige migração e registro na PR.
- Mudanças no sistema emocional devem separar: percepção/appraisal, transição de estado, persistência, relacionamento e apresentação.
- Estado de usuário nunca pode ficar em singleton global ou ser compartilhado entre requisições.

## Segurança e produto

- Nunca confie em `user_id` enviado pelo cliente sem validar a identidade autenticada.
- Não adicione segredos ao repositório, logs ou corpo da PR.
- Não introduza instruções de engano sobre a natureza do sistema, manipulação emocional, coerção ou sexualização por padrão.
- Dados emocionais e memórias são dados sensíveis: aplique minimização, isolamento por usuário e autorização.

## Qualidade mínima

Antes de abrir a PR:

1. Execute os testes relevantes e registre os comandos e resultados.
2. Adicione ou atualize testes para toda regra de domínio alterada.
3. Verifique estados limite, concorrência e falhas de integração quando aplicável.
4. Mantenha a PR pequena e revisável; divida tarefas maiores em etapas independentes.
5. Não deixe `print` de depuração, código morto, TODO sem issue ou tratamento genérico que esconda erros.

## Formato da PR

O comentário inicial/corpo da PR deve conter:

- Issue/tarefa de origem.
- Problema e causa raiz.
- Solução e decisões tomadas.
- Arquivos/áreas afetadas.
- Testes executados e resultado.
- Riscos, migração e rollback.
- Itens deliberadamente fora de escopo.

Use Conventional Commits e títulos como `feat(emotion): ...`, `fix(auth): ...` ou `test(emotion): ...`.
