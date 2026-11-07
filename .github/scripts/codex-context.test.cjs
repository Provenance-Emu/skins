const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { command, prepare } = require('./codex-context.cjs');

function fixture(t, eventName = 'issue_comment') {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-context-'));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const outputs = {};
  const context = { eventName, repo: { owner: 'Provenance-Emu', repo: 'SkinKit' }, payload: {
    repository: { default_branch: 'main' }, sender: { login: 'maintainer', type: 'User' },
    comment: { body: '@codex fix this', user: { login: 'maintainer', type: 'User' } },
    issue: { number: 60 },
  } };
  const github = { rest: {
    repos: { getCollaboratorPermissionLevel: async () => ({ data: { permission: 'write' } }) },
    issues: {
      get: async () => ({ data: { title: 'Build failed', body: 'Broken', state: 'open', html_url: 'https://github.com/Provenance-Emu/SkinKit/issues/60' } }),
      listComments: async () => ({ data: [] }),
    },
    pulls: { list: async () => ({ data: [] }) },
    actions: { listJobsForWorkflowRun: () => {},
      downloadJobLogsForWorkflowRun: async () => ({ data: 'actual failure log' }) },
  }, paginate: async () => [{ id: 123, name: 'build', conclusion: 'failure' }] };
  return { github, context, temp, outputs, core: { setOutput: (k, v) => outputs[k] = v, info: () => {} } };
}

test('recognizes an explicit fix command without intercepting reviews or quoted mentions', () => {
  for (const value of ['@codex fix', ' @CODEX fix the CI\nthanks']) assert.ok(command(value));
  for (const value of ['@codex review', '@codex security review', 'please @codex fix', '@codex fixture', '> @codex fix']) assert.ok(!command(value));
});

test('trusted command prepares a scoped issue repair', async t => {
  const f = fixture(t);
  await prepare(f);
  assert.equal(f.outputs.run, 'true');
  assert.equal(f.outputs.branch, 'ci/codex-issue-60');
  assert.match(fs.readFileSync(path.join(f.temp, 'codex-prompt.txt'), 'utf8'), /BEGIN UNTRUSTED CONTEXT/);
});

test('read-only users cannot start a secret-bearing job', async t => {
  const f = fixture(t);
  f.github.rest.repos.getCollaboratorPermissionLevel = async () => ({ data: { permission: 'read' } });
  await prepare(f);
  assert.equal(f.outputs.run, undefined);
});

test('bot commands cannot start a repair', async t => {
  const f = fixture(t);
  f.context.payload.comment.user.type = 'Bot';
  await prepare(f);
  assert.equal(f.outputs.run, undefined);
});

test('existing repair PR prevents repeated automatic fixes', async t => {
  const f = fixture(t);
  f.github.rest.pulls.list = async () => ({ data: [{ html_url: 'existing' }] });
  await prepare(f);
  assert.equal(f.outputs.run, undefined);
});

function failure(f) {
  f.context.payload.workflow_run = { id: 9, workflow_id: 4, name: 'CI', conclusion: 'failure',
    event: 'push', head_branch: 'main', head_repository: { full_name: 'Provenance-Emu/SkinKit' }, html_url: 'run' };
}

test('default-branch failure includes failed job logs', async t => {
  const f = fixture(t, 'workflow_run');
  failure(f);
  await prepare(f);
  assert.equal(f.outputs.branch, 'ci/codex-workflow-4');
  assert.match(fs.readFileSync(path.join(f.temp, 'codex-prompt.txt'), 'utf8'), /actual failure log/);
});

test('scheduled and manually dispatched default-branch failures can be repaired', async t => {
  for (const event of ['schedule', 'workflow_dispatch']) {
    const f = fixture(t, 'workflow_run');
    failure(f);
    f.context.payload.workflow_run.event = event;
    await prepare(f);
    assert.equal(f.outputs.run, 'true');
  }
});

test('linked failure logs are restricted to the current repository', async t => {
  const f = fixture(t);
  f.github.rest.issues.get = async () => ({ data: { title: 'failure', state: 'open',
    body: 'https://github.com/another/private-repo/actions/runs/42', html_url: 'issue' } });
  f.github.rest.actions.getWorkflowRun = async () => { throw new Error('must not fetch foreign run'); };
  await prepare(f);
  assert.equal(f.outputs.run, 'true');
});

test('same-repository failure URL supplies logs for a manual fix', async t => {
  const f = fixture(t);
  failure(f);
  f.github.rest.issues.get = async () => ({ data: { title: 'failure', state: 'open',
    body: 'https://github.com/Provenance-Emu/SkinKit/actions/runs/9', html_url: 'issue' } });
  f.github.rest.actions.getWorkflowRun = async ({ run_id }) => {
    assert.equal(run_id, 9);
    return { data: f.context.payload.workflow_run };
  };
  await prepare(f);
  assert.match(fs.readFileSync(path.join(f.temp, 'codex-prompt.txt'), 'utf8'), /actual failure log/);
});

test('PR request supplies context while retaining the default branch as base', async t => {
  const f = fixture(t);
  f.github.rest.issues.get = async () => ({ data: { title: 'PR', state: 'open',
    body: 'fix my PR', pull_request: {}, html_url: 'pr' } });
  f.github.rest.pulls.get = async () => ({ data: 'untrusted branch diff' });
  await prepare(f);
  assert.equal(f.outputs.base, 'main');
  assert.match(fs.readFileSync(path.join(f.temp, 'codex-prompt.txt'), 'utf8'), /untrusted branch diff/);
});

test('PR, fork, feature-branch, and successful runs are ignored', async t => {
  for (const edit of [r => r.event = 'pull_request', r => r.head_branch = 'feature',
    r => r.head_repository.full_name = 'attacker/fork', r => r.conclusion = 'success']) {
    const f = fixture(t, 'workflow_run');
    failure(f);
    edit(f.context.payload.workflow_run);
    await prepare(f);
    assert.equal(f.outputs.run, undefined);
  }
});

test('codex label and manual dispatch are gated by maintainer access', async t => {
  for (const event of ['issues', 'workflow_dispatch']) {
    const f = fixture(t, event);
    delete f.context.payload.comment;
    f.context.payload.label = { name: 'codex' };
    f.context.payload.inputs = { issue_number: '60' };
    await prepare(f);
    assert.equal(f.outputs.run, 'true');
  }
});
