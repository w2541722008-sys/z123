const fs = require('fs');
const path = require('path');

function extractHandlerActions(sourceContent) {
    const actions = new Set();
    const actionSources = new Map();
    const handlerObjectNames = [
        'CHARACTER_ACTION_HANDLERS',
        'ADVANCED_ACTION_HANDLERS',
        'MEMBERSHIP_ACTION_HANDLERS',
        'DASHBOARD_ACTION_HANDLERS',
    ];

    for (const objectName of handlerObjectNames) {
        const objectBody = extractObjectLiteralBody(sourceContent, objectName);
        if (!objectBody) continue;
        const regex = /'([a-z0-9-]+)'\s*:/g;
        let match;
        while ((match = regex.exec(objectBody)) !== null) {
            const action = match[1];
            actions.add(action);
            if (!actionSources.has(action)) {
                actionSources.set(action, []);
            }
            actionSources.get(action).push(objectName);
        }
    }

    const duplicateActions = Array.from(actionSources.entries())
        .filter(([, sources]) => sources.length > 1)
        .map(([action, sources]) => ({ action, sources }))
        .sort((a, b) => a.action.localeCompare(b.action));

    return { actions, duplicateActions };
}

function extractObjectLiteralBody(source, objectName) {
    const marker = `const ${objectName} = {`;
    const startIndex = source.indexOf(marker);
    if (startIndex === -1) return '';
    const braceStart = source.indexOf('{', startIndex);
    if (braceStart === -1) return '';

    let depth = 0;
    for (let i = braceStart; i < source.length; i++) {
        const ch = source[i];
        if (ch === '{') depth += 1;
        if (ch === '}') {
            depth -= 1;
            if (depth === 0) {
                return source.slice(braceStart + 1, i);
            }
        }
    }
    return '';
}

function extractHtmlActions(indexHtmlContent) {
    const actions = new Set();
    const regex = /data-action="([^"]+)"/g;
    let match;
    while ((match = regex.exec(indexHtmlContent)) !== null) {
        actions.add(match[1]);
    }
    return actions;
}

function listJsFiles(dirPath) {
    const results = [];
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const entry of entries) {
        const absPath = path.join(dirPath, entry.name);
        if (entry.isDirectory()) {
            results.push(...listJsFiles(absPath));
        } else if (entry.isFile() && entry.name.endsWith('.js')) {
            results.push(absPath);
        }
    }
    return results;
}

function extractDynamicActions(adminJsDir) {
    const actions = new Set();
    const files = listJsFiles(adminJsDir);
    const regex = /data-action=["']([a-z0-9-]+)["']/g;
    for (const filePath of files) {
        const content = fs.readFileSync(filePath, 'utf8');
        let match;
        while ((match = regex.exec(content)) !== null) {
            actions.add(match[1]);
        }
    }
    return actions;
}

function getArgValue(prefix) {
    const arg = process.argv.find((item) => item.startsWith(prefix));
    if (!arg) return '';
    return arg.slice(prefix.length);
}

function readAllowList(projectRoot, allowListArg) {
    if (!allowListArg) {
        return { allowSet: new Set(), grouped: new Map() };
    }
    const allowListPath = path.isAbsolute(allowListArg)
        ? allowListArg
        : path.join(projectRoot, allowListArg);
    const raw = fs.readFileSync(allowListPath, 'utf8');
    const parsed = JSON.parse(raw);

    const grouped = new Map();
    const allowSet = new Set();

    if (Array.isArray(parsed)) {
        grouped.set('default', parsed.map((name) => String(name)));
    } else if (parsed && typeof parsed === 'object' && parsed.modules && typeof parsed.modules === 'object') {
        for (const [moduleName, actionList] of Object.entries(parsed.modules)) {
            if (!Array.isArray(actionList)) {
                throw new Error(`allow-list 模块 ${moduleName} 必须是数组`);
            }
            grouped.set(moduleName, actionList.map((name) => String(name)));
        }
    } else {
        throw new Error('allow-list 必须是 JSON 数组或 { modules: { ... } } 结构');
    }

    for (const names of grouped.values()) {
        for (const name of names) {
            allowSet.add(name);
        }
    }

    return { allowSet, grouped };
}

function invertModuleActions(grouped) {
    const actionToModules = new Map();
    for (const [moduleName, actions] of grouped.entries()) {
        for (const action of actions) {
            if (!actionToModules.has(action)) {
                actionToModules.set(action, []);
            }
            actionToModules.get(action).push(moduleName);
        }
    }
    return actionToModules;
}

function runCheck() {
    const strictMode = process.argv.includes('--strict');
    const allowListArg = getArgValue('--allow-list=');
    const projectRoot = path.resolve(__dirname, '..');
    const actionsJsPath = path.join(projectRoot, 'frontend', 'admin', 'js', 'actions.js');
    const adminJsDir = path.join(projectRoot, 'frontend', 'admin', 'js');
    const adminHtmlPath = path.join(projectRoot, 'frontend', 'admin', 'index.html');

    const actionsJsContent = fs.readFileSync(actionsJsPath, 'utf8');
    const indexHtmlContent = fs.readFileSync(adminHtmlPath, 'utf8');
    const { allowSet, grouped } = readAllowList(projectRoot, allowListArg);
    const actionToModules = invertModuleActions(grouped);

    const { actions: handlerActions, duplicateActions } = extractHandlerActions(actionsJsContent);
    const htmlActions = extractHtmlActions(indexHtmlContent);
    const dynamicActions = extractDynamicActions(adminJsDir);
    const usedActions = new Set([...htmlActions, ...dynamicActions]);

    const missingInHandlers = Array.from(usedActions).filter((name) => !handlerActions.has(name)).sort();
    const unreferencedHandlers = Array.from(handlerActions).filter((name) => !usedActions.has(name)).sort();
    const unresolvedUnusedHandlers = unreferencedHandlers.filter((name) => !allowSet.has(name));
    const staleAllowList = Array.from(allowSet).filter((name) => !unreferencedHandlers.includes(name)).sort();

    if (duplicateActions.length > 0) {
        console.error('❌ admin action 在多个处理器映射中重复定义（会发生覆盖）:');
        duplicateActions.forEach(({ action, sources }) => {
            console.error(`  - ${action}: ${sources.join(' -> ')}`);
        });
        process.exit(1);
    }

    if (missingInHandlers.length > 0) {
        console.error('❌ admin data-action 未在 actions.js 处理器中定义:');
        missingInHandlers.forEach((name) => console.error(`  - ${name}`));
        process.exit(1);
    }

    if (staleAllowList.length > 0) {
        console.error('⚠️ allow-list 中存在已不需要豁免的 action:');
        staleAllowList.forEach((name) => {
            const modules = actionToModules.get(name) || [];
            const moduleText = modules.length > 0 ? ` [${modules.join(', ')}]` : '';
            console.error(`  - ${name}${moduleText}`);
        });
    }

    if (allowListArg && unresolvedUnusedHandlers.length === 0 && unreferencedHandlers.length > 0) {
        console.error('ℹ️ 当前未被静态+动态引用的 handler 已全部由 allow-list 覆盖，按模块如下:');
        for (const [moduleName, actions] of grouped.entries()) {
            const hitActions = actions.filter((name) => unreferencedHandlers.includes(name));
            if (hitActions.length === 0) continue;
            console.error(`  - ${moduleName}: ${hitActions.join(', ')}`);
        }
    }

    if (unresolvedUnusedHandlers.length > 0) {
        const prefix = strictMode ? '❌' : '⚠️';
        const title = strictMode
            ? 'admin 处理器存在未被静态 HTML 使用的 action（严格模式失败）:'
            : 'admin 处理器存在未被静态 HTML 使用的 action（可能来自动态渲染）:';
        console.error(`${prefix} ${title}`);
        unresolvedUnusedHandlers.forEach((name) => console.error(`  - ${name}`));
        if (strictMode) {
            process.exit(1);
        }
    }

    const modeText = strictMode ? 'strict' : 'normal';
    const allowListText = allowListArg ? `，allow-list: ${allowSet.size}` : '';
    console.log(`✅ admin data-action 检查通过（mode: ${modeText}，HTML: ${htmlActions.size}，dynamic: ${dynamicActions.size}，handlers: ${handlerActions.size}${allowListText}）`);
}

runCheck();
