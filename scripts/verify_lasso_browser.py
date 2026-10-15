"""Real pointer checks against an already-open mathematical native workbench.

The full-cohort oracle reads synthetic EBI directly, independently of the
production scatter functions and the 10,000-point rendering sample.
"""
from __future__ import annotations

import struct


def inside(x, y, polygon):
    selected = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if abs(cross) < 1e-7 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= y <= max(a[1], b[1]):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            selected = not selected
    return selected


def oracle(source_root, request):
    paths = list(source_root.rglob('*.EBI'))
    assert len(paths) == 1
    rows = list(struct.iter_unpack('<IHHIIII', paths[0].read_bytes()[32:]))
    polygon = request['polygon']
    mode = request['mode']
    expected, boxed = [], []
    for previous, current, following in zip(rows, rows[1:], rows[2:]):
        groups = (previous[2], current[2], following[2])
        x, y = current[6], following[6]
        if not all(1 <= group <= 8 for group in groups):
            continue
        if mode == 'nn':
            if groups != (1, 1, 1) or not (300 <= x <= 2000 and 300 <= y <= 2000):
                continue
        elif not (0 < x <= 5000 and 0 < y <= 5000):
            continue
        wanted = {'n': 1, 's': 2, 'v': 3}.get(mode)
        if wanted and current[2] != wanted:
            continue
        if mode == 'hour' and not request['hour_start_s']*200 <= current[0] < (request['hour_start_s']+3600)*200:
            continue
        if min(p[0] for p in polygon) <= x <= max(p[0] for p in polygon) and min(p[1] for p in polygon) <= y <= max(p[1] for p in polygon):
            boxed.append(current[0])
        if inside(x, y, polygon):
            expected.append(current[0])
    return expected, boxed


async def verify_lasso(page, source_root, screenshot):
    checks = []
    await page.locator('.nav-item[data-page="edit"]').click()
    await page.locator('#editClusterMode').click()
    await page.wait_for_function("() => ECGTemplateLinkedView.context() && state.editScatterData?.points?.length")
    clinical = await page.evaluate('() => [...state.editSelectedSamples]')
    shape = [[850,850],[1150,850],[1150,1000],[1000,1000],[1000,1150],[850,1150],[850,850]]

    async def frame():
        await page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

    async def state():
        return await page.evaluate("""() => ({selection:ECGLinkedSelection.snapshot(),
            clinical:[...state.editSelectedSamples],linked:ECGTemplateLinkedView.context()?.samples,
            density:morphologyWorkbench.privateSnapshot()?.linked,stats:ECGTemplateLinkedView.stats()})""")

    async def draw(polygon, canvas='editScatterCanvas', release=True):
        points = await page.evaluate("""({polygon,canvas}) => {
            const c=document.getElementById(canvas),r=c.getBoundingClientRect(),b=state.editScatterData.bounds,
                lib=canvas.includes('Library'),left=lib?20:31,top=lib?6:10,
                width=r.width-left-(lib?6:9),height=r.height-top-(lib?16:22);
            return polygon.map(([x,y])=>[r.left+left+(x-b.x_min)/(b.x_max-b.x_min)*width,
                r.top+top+(b.y_max-y)/(b.y_max-b.y_min)*height]);
        }""", {'polygon': polygon, 'canvas': canvas})
        await page.mouse.move(*points[0])
        await page.mouse.down()
        for point in points[1:]:
            await page.mouse.move(*point, steps=8)
        if release:
            await page.mouse.up()

    async def select(polygon, canvas='editScatterCanvas'):
        before = (await state())['selection']['selectionGeneration']
        async with page.expect_response(lambda r: '/scatter-selection' in r.url and r.request.method == 'POST') as pending:
            await draw(polygon, canvas)
        response = await pending.value
        assert response.ok
        await page.wait_for_function("""generation => ECGLinkedSelection.snapshot().kind==='samples'
            && ECGLinkedSelection.snapshot().selectionGeneration>generation
            && morphologyWorkbench.privateSnapshot()?.linked?.phase==='ready'""", arg=before)
        await frame()
        return response.request.post_data_json, await state()

    request, selected = await select(shape)
    expected, boxed = oracle(source_root, request)
    assert expected and len(expected) < len(boxed), 'Concave fixture must exclude points inside its rectangle'
    assert selected['selection']['samples'] == expected, 'Lasso must match the complete independent EBI cohort'
    assert selected['selection']['origin'] == 'template-scatter-lasso'
    assert selected['clinical'] == clinical
    assert selected['density']['top']['total'] == len(selected['linked']) == selected['stats']['total']
    checks.append('concave-pointer-lasso-exact-full-EBI-cohort-and-linked-panels')
    await page.screenshot(path=str(screenshot))

    await draw([[400,400],[1500,400],[1500,1500]], release=False)
    await page.keyboard.press('Escape')
    await page.mouse.up()
    await frame()
    assert (await state())['selection']['samples'] == expected
    checks.append('escape-cancels-drag-and-preserves-cohort')

    await page.locator('#editLibraryMode').click()
    await frame()
    assert (await state())['selection']['samples'] == expected
    library_request, library = await select(shape, 'editLibraryScatterCanvas')
    assert library['selection']['samples'] == oracle(source_root, library_request)[0]
    assert library['clinical'] == clinical
    checks.append('library-lasso-preserves-independent-clinical-targets')
    await page.locator('#editClusterMode').click()
    await frame()

    _, empty = await select([[100,1500],[300,1500],[300,1700],[100,1700],[100,1500]])
    assert empty['selection']['samples'] == [] and empty['linked'] == []
    assert empty['density']['top']['total'] == empty['stats']['total'] == 0
    checks.append('empty-selection-is-empty-linked-population')
    request, repeated = await select(shape)
    assert repeated['selection']['samples'] == oracle(source_root, request)[0]
    request, repeated = await select(shape)
    assert repeated['selection']['samples'] == oracle(source_root, request)[0]
    checks.append('repeat-selection-retains-exact-membership')

    await page.set_viewport_size({'width':1280,'height':800})
    await frame()
    request, resized = await select(shape)
    assert resized['selection']['samples'] == oracle(source_root, request)[0]
    await draw([[400,400],[1400,400]], release=False)
    await page.mouse.wheel(0,50)
    await page.mouse.up()
    await frame()
    assert (await state())['selection']['samples'] == resized['selection']['samples']
    checks.append('resized-pointer-coordinates-and-wheel-cancellation')
    await page.locator('.edit-class-panel [data-lasso-clear]').click()
    await page.wait_for_function("() => ECGLinkedSelection.snapshot().kind==='none' && !morphologyWorkbench.privateSnapshot()?.linked")
    assert (await state())['clinical'] == clinical
    checks.append('clear-restores-full-population-without-changing-clinical-targets')
    await page.set_viewport_size({'width':1440,'height':1000})
    return {'checks':checks, 'selected_full_cohort':len(expected), 'bounding_box_cohort':len(boxed),
            'oracle':'independent struct EBI reader and even-odd polygon', 'clinical_targets_preserved':True}
