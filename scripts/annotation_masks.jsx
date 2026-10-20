// ChatGPT annotations are already mapped to the upright native canvas in Python.
// No Photoshop subject, sky, object detection or generative selection is called.
var PhotoAnnotationMasks = (function () {
    function canvasMatches(w, h, canvas) {
        if (!canvas || canvas.length !== 2) return false;
        var actual = [w, h];
        for (var i = 0; i < 2; i++) {
            if (typeof actual[i] !== 'number' || !isFinite(actual[i]) ||
                typeof canvas[i] !== 'number' || !isFinite(canvas[i]) ||
                canvas[i] < 1 || canvas[i] !== Math.round(canvas[i]) ||
                Math.abs(actual[i] - canvas[i]) > 0.000001) return false;
        }
        return true;
    }
    function apply(doc, region, canvas) {
        var w = doc.width.as('px'), h = doc.height.as('px');
        if (!canvasMatches(w, h, canvas)) {
            throw new Error('Annotation canvas differs from the native document; reannotate the actual baseline');
        }
        w = canvas[0]; h = canvas[1];
        var broad = region.broad_feather_px;
        if (broad !== undefined) {
            var positives = 0;
            for (var b = 0; b < region.contours.length; b++)
                if (region.contours[b].operation === 'add') {
                    positives++;
                    if (region.contours[b].feather_px !== 0) throw new Error('Broad contour must start unfeathered');
                }
            if (typeof broad !== 'number' || !isFinite(broad) || broad < 1 || broad > Math.min(1000, Math.min(w,h)/3) ||
                region.feather_mode !== 'per_contour' || region.feather_px !== 0 || positives !== 1)
                throw new Error('Invalid broad native feather');
        }
        doc.selection.deselect();
        var first = true;
        // Union all positive contours before subtracting holes, independent of JSON order.
        for (var pass = 0; pass < 2; pass++) {
            for (var i = 0; i < region.contours.length; i++) {
                var contour = region.contours[i];
                if ((pass === 0 && contour.operation !== 'add') || (pass === 1 && contour.operation !== 'subtract')) continue;
                var points = [];
                for (var j = 0; j < contour.points.length; j++) points.push([contour.points[j][0] * w, contour.points[j][1] * h]);
                var mode = first ? SelectionType.REPLACE : (pass === 0 ? SelectionType.EXTEND : SelectionType.DIMINISH);
                var contourFeather = region.feather_mode === 'per_contour' ? contour.feather_px : 0;
                if (typeof contourFeather !== 'number' || !isFinite(contourFeather) || contourFeather < 0 || contourFeather > 250)
                    throw new Error('Invalid contour feather: ' + region.id);
                doc.selection.select(points, mode, contourFeather, true);
                if (pass === 0 && broad !== undefined) {
                    // Repeated native feather passes broaden only the light field.
                    // Radius is an approximate equivalent scale, not a measured PS sigma.
                    // Later subtraction keeps the independently feathered shore/subject protection.
                    var count = Math.ceil((broad / 250) * (broad / 250));
                    var radius = broad / Math.sqrt(count);
                    for (var f = 0; f < count; f++) doc.selection.feather(radius);
                }
                first = false;
            }
        }
        try { var before = doc.selection.bounds; }
        catch (empty) { throw new Error('Model annotation selects no native pixels: ' + region.id); }
        if (region.invert) doc.selection.invert();
        if (region.feather_mode === 'per_contour' && region.feather_px !== 0)
            throw new Error('Independent contour feather cannot be blurred again');
        if (region.feather_px > 0) doc.selection.feather(region.feather_px);
        try { var after = doc.selection.bounds; }
        catch (empty2) { throw new Error('Inverted/feathered annotation is empty: ' + region.id); }
    }
    return {apply: apply, canvasMatches: canvasMatches};
}());
