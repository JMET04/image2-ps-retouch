// Executes photo-specific adjustments on original pixels. Image2 pixels are never imported.
(function () {
    var job = RETOUCH_JOB;
    var c = charIDToTypeID, s = stringIDToTypeID;
    var oldDialogs = app.displayDialogs, oldUnits = app.preferences.rulerUnits;
    var doc = null, exported = null;
    app.displayDialogs = DialogModes.NO;
    app.preferences.rulerUnits = Units.PIXELS;
    function curves(step) {
        var d = new ActionDescriptor(), r = new ActionReference();
        r.putClass(c('AdjL')); d.putReference(c('null'), r);
        var layer = new ActionDescriptor(), settings = new ActionDescriptor(), list = new ActionList();
        var channels = {composite:'Cmps', red:'Rd  ', green:'Grn ', blue:'Bl  '};
        for (var key in step.channels) {
            var curve = new ActionDescriptor(), ref = new ActionReference(), pts = new ActionList();
            ref.putEnumerated(c('Chnl'), c('Chnl'), c(channels[key])); curve.putReference(c('Chnl'), ref);
            var points = step.channels[key];
            for (var i=0; i<points.length; i++) {
                var point = new ActionDescriptor(); point.putDouble(c('Hrzn'), points[i][0]); point.putDouble(c('Vrtc'), points[i][1]);
                pts.putObject(c('Pnt '), point);
            }
            curve.putList(c('Crv '), pts); list.putObject(c('CrvA'), curve);
        }
        settings.putList(c('Adjs'), list); layer.putObject(c('Type'), c('Crvs'), settings);
        d.putObject(c('Usng'), c('AdjL'), layer); executeAction(c('Mk  '), d, DialogModes.NO);
    }
    function hueSaturation(step) {
        var d = new ActionDescriptor(), r = new ActionReference(); r.putClass(c('AdjL')); d.putReference(c('null'), r);
        var layer = new ActionDescriptor(), settings = new ActionDescriptor(), list = new ActionList(), adj = new ActionDescriptor();
        settings.putEnumerated(s('presetKind'),s('presetKindType'),s('presetKindCustom'));
        settings.putBoolean(c('Clrz'),false); adj.putInteger(c('H   '),step.hue || 0);
        adj.putInteger(c('Strt'),step.saturation || 0); adj.putInteger(c('Lght'),step.lightness || 0);
        list.putObject(c('Hst2'),adj); settings.putList(c('Adjs'),list);
        layer.putObject(c('Type'),c('HStr'),settings); d.putObject(c('Usng'),c('AdjL'),layer);
        executeAction(c('Mk  '),d,DialogModes.NO);
    }
    function selectRegion(region) {
        doc.selection.deselect(); if (!region) return;
        if (region.kind==='annotated') {
            PhotoAnnotationMasks.apply(doc,region,job.annotation_canvas);
            return;
        }
        var w=doc.width.as('px'), h=doc.height.as('px'), points=[];
        if (region.kind==='polygon') {
            for(var i=0;i<region.points.length;i++) points.push([region.points[i][0]*w,region.points[i][1]*h]);
            doc.selection.select(points);
        } else if(region.kind==='ellipse') {
            var b=region.bounds, cx=(b[0]+b[2])*w/2, cy=(b[1]+b[3])*h/2, rx=(b[2]-b[0])*w/2, ry=(b[3]-b[1])*h/2;
            for(var j=0;j<64;j++){var t=2*Math.PI*j/64;points.push([cx+rx*Math.cos(t),cy+ry*Math.sin(t)]);}
            doc.selection.select(points);
        } else {
            throw new Error('Photoshop automatic recognition is disabled; use reviewed model annotations');
        }
        try { var selectionBounds=doc.selection.bounds; }
        catch(emptySelection) { throw new Error('Region selection is empty: '+region.kind); }
        if(region.invert) doc.selection.invert();
        var feather=Math.min(w,h)*(region.feather_fraction === undefined ? .01 : region.feather_fraction);
        if(feather>0) doc.selection.feather(feather);
    }
    function exportJPEG(path) {
        exported=doc.duplicate(); app.activeDocument=exported;
        exported.flatten(); exported.convertProfile('sRGB IEC61966-2.1',Intent.RELATIVECOLORIMETRIC,true,true);
        exported.bitsPerChannel=BitsPerChannelType.EIGHT;
        var opt=new JPEGSaveOptions();opt.quality=12;opt.embedColorProfile=true;opt.formatOptions=FormatOptions.STANDARDBASELINE;
        exported.saveAs(new File(path),opt,true,Extension.LOWERCASE);
        exported.close(SaveOptions.DONOTSAVECHANGES);exported=null;app.activeDocument=doc;
    }
    try {
        var source=new File(job.source), ext=source.name.split('.').pop().toLowerCase();
        // Purge is application-wide. Allow it only when there are no user documents.
        var purgeOwnedHistory = job.scratch_history_policy === 'discard_owned_history';
        if(purgeOwnedHistory && app.documents.length!==0) {
            throw new Error('Owned history purge requires zero existing documents');
        }
        // Never reuse or close a user's already-open document, including unsaved edits.
        for (var existing=0; existing<app.documents.length; existing++) {
            var existingFile=null;
            try { existingFile=app.documents[existing].fullName; } catch(unsavedDocument) {}
            if (existingFile && existingFile.fsName.toLowerCase()===source.fsName.toLowerCase()) {
                throw new Error('Original is already open in Photoshop; save/close it or use a separate source copy');
            }
        }
        if(/^(cr2|cr3|nef|arw|dng)$/.test(ext)) {
            var raw=new CameraRAWOpenOptions(); raw.settings=CameraRAWSettingsType.CAMERA;
            raw.bitsPerChannel=BitsPerChannelType.SIXTEEN; raw.colorSpace=ColorSpaceType.ADOBERGB;
            doc=app.open(source,raw);
        } else { doc=app.open(source); }
        if(doc.mode!==DocumentMode.RGB) doc.changeMode(ChangeMode.RGB);
        if(job.annotation_canvas && !PhotoAnnotationMasks.canvasMatches(doc.width.as('px'),doc.height.as('px'),job.annotation_canvas)) {
            throw new Error('Native decoding dimensions differ from the annotated baseline');
        }
        if (job.input_profile) {
            // Assignment specifies known source interpretation; it is not a pixel conversion.
            doc.colorProfileName=job.input_profile;
        } else if (doc.colorProfileType===ColorProfile.NONE) {
            throw new Error('Untagged source: determine and record its input profile before retouching');
        }
        if(job.stage==='prepare') {
            exportJPEG(job.output_base+'_baseline.jpg');
            var result='Prepared '+doc.width.as('px')+'x'+doc.height.as('px')+' baseline';
            doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;return result;
        }
        doc.bitsPerChannel=BitsPerChannelType.SIXTEEN;
        doc.activeLayer.name='原片 · 像素保留';
        if(job.straighten_transform || job.working_profile) {
            // Preserve the unrotated original decode inside an embedded smart object.
            executeAction(s('newPlacedLayer'),undefined,DialogModes.NO);
            doc.activeLayer.name='原片 · 内嵌未校正像素';
        }
        if(job.working_profile) {
            // Preserve source decode inside the smart object; apply fitted curves
            // in the same explicit RGB space used by the reference comparison.
            doc.convertProfile(job.working_profile,Intent.RELATIVECOLORIMETRIC,true,true);
        }
        for(var n=0;n<job.steps.length;n++) {
            var step=job.steps[n]; app.activeDocument=doc;selectRegion(step.region);
            if(step.kind==='curves')curves(step);else hueSaturation(step);
            doc.activeLayer.name=step.name;doc.activeLayer.opacity=step.opacity === undefined ? 100 : step.opacity;
            if(step.blend==='luminosity')doc.activeLayer.blendMode=BlendMode.LUMINOSITY;
            if(step.blend==='color')doc.activeLayer.blendMode=BlendMode.COLORBLEND;
            doc.selection.deselect();
            if(purgeOwnedHistory) {
                if(app.documents.length!==1 || app.activeDocument!==doc) {
                    throw new Error('Another document appeared; refusing application-wide purge');
                }
                // Adjustment layers remain editable; only this job's undo/history is discarded.
                app.purge(PurgeTarget.HISTORYCACHES);
            }
        }
        if(job.straighten_transform) {
            var t=job.straighten_transform;
            doc.rotateCanvas(t.clockwise_degrees);
            var rw=doc.width.as('px'),rh=doc.height.as('px');
            var left=Math.round(rw/2+t.center_offset[0]-t.crop_size[0]/2);
            var top=Math.round(rh/2+t.center_offset[1]-t.crop_size[1]/2);
            doc.crop([UnitValue(left,'px'),UnitValue(top,'px'),
                UnitValue(left+t.crop_size[0],'px'),UnitValue(top+t.crop_size[1],'px')]);
            if(!PhotoAnnotationMasks.canvasMatches(doc.width.as('px'),doc.height.as('px'),t.crop_size)) {
                throw new Error('Native straightening crop dimensions differ from the reviewed plan');
            }
        } else if(job.crop) {
            var b=job.crop,w=doc.width.as('px'),h=doc.height.as('px');
            // Crop is recorded; the untouched source remains available separately.
            doc.crop([UnitValue(b[0]*w,'px'),UnitValue(b[1]*h,'px'),UnitValue(b[2]*w,'px'),UnitValue(b[3]*h,'px')]);
        }
        if(job.save_psd !== false) {
            var opt=new PhotoshopSaveOptions();opt.layers=true;opt.embedColorProfile=true;opt.alphaChannels=true;
            doc.saveAs(new File(job.output_base+'.psd'),opt,true,Extension.LOWERCASE);
        }
        exportJPEG(job.output_base+'.jpg');
        var result=(job.save_psd === false ? 'Exported working JPEG from ' : 'Saved ')+doc.layers.length+' layers, '+doc.width.as('px')+'x'+doc.height.as('px');
        doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;return result;
    } catch(e) {
        // A failed marked selection or adjustment is not replaced by a global preset.
        throw new Error('Retouch failed: '+e.message+' at line '+e.line);
    } finally {
        if(exported){try{exported.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
        if(doc){try{doc.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore2){}}
        app.displayDialogs=oldDialogs;app.preferences.rulerUnits=oldUnits;
    }
}());
