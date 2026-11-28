"""Run separately with QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QWidget, QStyle, QStyleOptionViewItem
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QColor, QImage, QEnterEvent
from unittest.mock import patch
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocketServer
import floating_dictionary as floating
from test_performance import database
import async_lookup
import hover_lookup
import yomitan_goldendict as manager_module

app=QApplication([])

def wait_until(condition, seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
        if condition():return
    raise AssertionError('Timed out')

def js(code):
    result=[]
    window.web.page().runJavaScript(code,lambda value:result.append(value))
    wait_until(lambda:bool(result))
    return result[0]

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    path=root/'test.sqlite3';fixture=database(path)
    fixture.execute("ALTER TABLE dictionaries ADD COLUMN path TEXT DEFAULT 'test.zip'")
    fixture.execute("ALTER TABLE dictionaries ADD COLUMN count INTEGER DEFAULT 1")
    fixture.execute("ALTER TABLE dictionaries ADD COLUMN stamp TEXT")
    fixture.execute("UPDATE dictionaries SET path='dict-' || id || '.zip'")
    fixture.commit();fixture.close()
    manager_module.DB_PATH=path
    manager_module.APP_DIR=root
    migrated=manager_module.connect();migrated.close()
    gif=root/'background.gif';gif.write_bytes(base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'))
    floating.CONFIG_DIR=root
    floating.CONFIG_FILE=root/'settings.json'
    floating.CONFIG_FILE.write_text(json.dumps({'auto_fade':False,'background_image':str(gif),'avatar_folder':str(root),'avatar_seconds':3,'background_folder':str(root)}))
    floating.SOCKET_NAME='yomitan-test-'+str(os.getpid())
    floating.connect=lambda:sqlite3.connect(path)
    # Prevent display-service calls from this isolated headless test.
    floating.FloatingDictionary.apply_background_blur=lambda self:None
    # Use an isolated GSM fixture rather than subscribing to the user's live reading.
    feed_server=QWebSocketServer('GSM fixture',QWebSocketServer.SslMode.NonSecureMode)
    assert feed_server.listen(QHostAddress('127.0.0.1'),0)
    feed_clients=[]
    def feed_connected():
        client=feed_server.nextPendingConnection();feed_clients.append(client)
        client.textMessageReceived.connect(lambda _:client.sendTextMessage(json.dumps({'event':'text_v2_snapshot','lines':[
            {'id':'stats-1','session_id':'test','text':'日本語123！','revision':0,'scene':'Test book'}]})))
    feed_server.newConnection.connect(feed_connected)
    real_anki_feed=floating.AnkiStatsFeed
    floating.AnkiStatsFeed=lambda database,paths,changed,parent:real_anki_feed(database,[],changed,parent)
    real_feed=floating.StatsFeed
    floating.StatsFeed=lambda store,changed,parent,**kwargs:real_feed(store,changed,parent,url=f'ws://127.0.0.1:{feed_server.serverPort()}/ws/texthooker')
    original_lookup=async_lookup.lookup
    async_lookup.lookup=lambda query,cancelled:original_lookup(query,cancelled,path)
    original_hover=hover_lookup.hover_lookup
    hover_lookup.hover_lookup=lambda payload,cancelled,**kwargs:original_hover(payload,cancelled,path,**kwargs)
    sources=floating.StatsSettings(root)
    sources.save({'mokuro_browser':{'path':str(root/'mokuro-browser.sqlite3')}})
    window=floating.FloatingDictionary()
    window.show()
    shortcut_client=None
    try:
        wait_until(lambda:window.page_loaded)
        assert js("getComputedStyle(document.getElementById('clear-query')).display")=='none'
        assert js("getComputedStyle(document.getElementById('secondary-clear')).display")=='none'
        assert not js("!!document.getElementById('toolbar-tools-toggle')")
        assert js("getComputedStyle(document.getElementById('toolbar-tool-items')).visibility")=='visible'
        assert js("document.getElementById('reading-stats-button').parentElement.id==='toolbar'")
        assert js("document.getElementById('dictionaries').parentElement.classList.contains('toolbar-right')")
        assert js("!!document.querySelector('#pin svg') && !pin.classList.contains('active')")
        js('updateKeepAbove(true)');pinned_transform=js("getComputedStyle(pin.querySelector('svg')).transform")
        js('updateKeepAbove(false)');assert js("getComputedStyle(pin.querySelector('svg')).transform")!=pinned_transform
        assert js("getComputedStyle(pin).backgroundColor")=='rgba(0, 0, 0, 0)'
        assert js("pin.nextElementSibling.id")=='pane-stay-visible'
        assert js("document.getElementById('pane-stay-visible').getAttribute('aria-pressed')")=='true'
        js("document.getElementById('pane-stay-visible').click()")
        wait_until(lambda:window.settings['auto_fade'])
        assert floating.load_settings()['auto_fade']
        js("document.getElementById('pane-stay-visible').click()")
        wait_until(lambda:not window.settings['auto_fade'])
        assert not floating.load_settings()['auto_fade']
        js('panelHovered=false;nativePanelHovered=false;imageHovered=false;setWindowActive(false);scheduleFade()')
        QTest.qWait(1200)
        assert js("!panel.classList.contains('faded')") and window.panel_visible
        js('setWindowActive(true)')
        js("document.getElementById('lookup-split').click()")
        wait_until(lambda:window.settings['lookup_split'])
        js("setQuery('先生');app.search(query.value);secondaryQuery.value='先制';secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:js("document.querySelector('#results .entry h3')?.textContent==='先生' && document.querySelector('#secondary-results .entry h3')?.textContent==='先制'"))
        assert window.query=='先生' and window.secondary_query=='先制'
        divider_center=json.loads(js("(()=>{const r=document.getElementById('lookup-divider').getBoundingClientRect();return JSON.stringify([r.x+r.width/2,r.y+30]);})()"))
        QTest.mousePress(window.web.focusProxy(),Qt.MouseButton.LeftButton,pos=QPoint(round(divider_center[0]),round(divider_center[1])))
        QTest.mouseMove(window.web.focusProxy(),QPoint(round(divider_center[0]-50),round(divider_center[1])))
        QTest.mouseRelease(window.web.focusProxy(),Qt.MouseButton.LeftButton,pos=QPoint(round(divider_center[0]-50),round(divider_center[1])))
        wait_until(lambda:window.settings['lookup_column_weights'][0]<.48)
        assert floating.load_settings()['lookup_column_weights']==window.settings['lookup_column_weights']
        js("divider.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}))")
        wait_until(lambda:window.settings['lookup_column_weights'][0]==.5)

        js("secondaryQuery.dispatchEvent(new CompositionEvent('compositionstart'));secondaryQuery.value='せ';secondaryQuery.dispatchEvent(new InputEvent('input',{isComposing:true}))")
        QTest.qWait(250)
        assert window.secondary_query=='先制'
        js("secondaryQuery.value='せんせい';secondaryQuery.dispatchEvent(new CompositionEvent('compositionend'))")
        wait_until(lambda:window.secondary_query=='せんせい')
        js("secondaryQuery.value='先?';secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        QTest.qWait(250)
        assert window.secondary_query=='せんせい'
        js("secondaryQuery.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
        wait_until(lambda:window.secondary_query=='先?')
        assert window.query=='先生'
        js("secondaryQuery.value='先制';secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:window.secondary_query=='先制' and window.secondary_worker.pending is None)

        # Repeated add controls grow a rectangular grid without replacing old searches.
        assert js("getComputedStyle(document.getElementById('lookup-split')).backgroundColor")=='rgba(0, 0, 0, 0)'
        js("for(let i=0;i<9;i++)document.getElementById('lookup-split').click()")
        wait_until(lambda:len(window.settings['lookup_grid'][0])==11)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==11
        js("const third=lookupCells.get(2).input;third.value='先';third.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:js("lookupCells.get(2).output.querySelector('.entry h3')?.textContent==='先'"))
        assert window.extra_queries[2]=='先' and window.query=='先生' and window.secondary_query=='先制'
        assert {row['query'] for row in window.search_history.entries()} >= {'先生','先制','先'}
        js("lookupCells.get(2).root.querySelector('.search-icon').click()")
        wait_until(lambda:js("document.querySelectorAll('.search-history-entry').length>=3"))
        assert js("(()=>{const cell=lookupCells.get(2),history=document.querySelector('.search-history-popup'),h=history.getBoundingClientRect(),r=cell.output.getBoundingClientRect(),c=cell.content.getBoundingClientRect();return history.parentElement===cell.content&&Math.abs(h.top-c.top)<1&&Math.abs(h.bottom-c.bottom)<1&&h.right<=r.left;})()")
        assert js("getComputedStyle(document.querySelector('.search-history-list')).overflowY")=='auto'
        js("window.dispatchEvent(new Event('resize'))")
        assert js("!!document.querySelector('.search-history-popup')")
        assert js("document.querySelector('.search-history-sort').textContent")=='↓ Newest first'
        js("document.querySelector('.search-history-sort').click()")
        wait_until(lambda:js("document.querySelector('.search-history-sort').textContent==='↑ Oldest first'"))
        js("[...document.querySelectorAll('.search-history-entry')].find(row=>row.querySelector('.search-history-headword').textContent==='先生').click()")
        wait_until(lambda:window.extra_queries[2]=='先生')
        assert not js("!!document.querySelector('.search-history-popup')")
        assert js("lookupCells.get(2).input.value")=='先生'
        js("lookupCells.get(2).root.querySelector('.search-icon').click()")
        wait_until(lambda:js("!!document.querySelector('.search-history-popup')"))
        js("lookupCells.get(2).input.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))")
        assert not js("!!document.querySelector('.search-history-popup')")
        js("lookupCells.get(2).input.value='先';submitLookup(2)")
        wait_until(lambda:window.extra_queries[2]=='先')
        assert window.extra_workers[2].executor is window.secondary_worker.executor
        js("document.getElementById('lookup-add-row').click();document.getElementById('lookup-add-row').click()")
        wait_until(lambda:len(window.settings['lookup_grid'])==3)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==33
        assert js("lookupCells.get(2).input.value")=='先'
        assert floating.load_settings()['lookup_grid']==window.settings['lookup_grid']
        js("resetLookupGrid();for(let i=0;i<4;i++)document.getElementById('lookup-split').click();document.getElementById('lookup-add-row').click()")
        wait_until(lambda:len(window.settings['lookup_grid'])==2 and len(window.settings['lookup_grid'][0])==5)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==10
        js("document.getElementById('lookup-add-row').click()")
        wait_until(lambda:len(window.settings['lookup_grid'])==3)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==15
        js("document.querySelector('.lookup-grid-divider[data-axis=row]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))")
        wait_until(lambda:window.settings['lookup_row_weights'][0]>1/3)
        assert floating.load_settings()['lookup_row_weights']==window.settings['lookup_row_weights']
        js("document.getElementById('lookup-split').click()")
        wait_until(lambda:len(window.settings['lookup_grid'][0])==6)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==18
        QTest.qWait(100);window.web.grab().save('/tmp/ukijiten-lookup-grid.png')
        js("resetLookupGrid();for(let i=0;i<10;i++)document.getElementById('lookup-add-row').click()")
        wait_until(lambda:len(window.settings['lookup_grid'])==11)
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==11
        js("resetLookupGrid();document.getElementById('lookup-split').click()")
        wait_until(lambda:window.settings['lookup_grid']==[[0,1]])

        # Tiny dots close one search; closing the first promotes its neighbour.
        assert not js("lookupArea.textContent.includes('Type a word to look it up')")
        assert not js("lookupCells.get(0).close.hidden")
        js("document.getElementById('lookup-split').click();const extra=lookupCells.get(2).input;extra.value='先';extra.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:js("lookupCells.get(2).output.querySelector('.entry h3')?.textContent==='先'"))
        js("lookupCells.get(0).close.click()")
        wait_until(lambda:window.settings['lookup_grid']==[[0,2]] and window.query=='先制')
        assert js("query.value")=='先制' and js("lookupCells.get(2).input.value")=='先'
        js("lookupCells.get(2).close.click()")
        wait_until(lambda:window.settings['lookup_grid']==[[0]])
        assert js("lookupCells.get(0).close.hidden")
        assert js("document.getElementById('lookup-close-extras').hidden")
        js("document.getElementById('lookup-split').click();document.getElementById('lookup-add-row').click()")
        wait_until(lambda:len(window.settings['lookup_grid'])==2)
        js("document.getElementById('lookup-close-extras').click()")
        wait_until(lambda:window.settings['lookup_grid']==[[0]])
        assert js("query.value")=='先制'
        assert js("document.querySelectorAll('.lookup-pane:not([hidden])').length")==1
        js("document.getElementById('lookup-split').click();query.value='先生';app.search(query.value);secondaryQuery.value='先制';secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:window.settings['lookup_grid']==[[0,1]] and window.secondary_query=='先制')
        wait_until(lambda:js("results.querySelector('.entry h3')?.textContent==='先生'"))
        assert js("[...lookupArea.querySelectorAll('.dictionary-nav-toggle')].every(button=>['↓','↑'].includes(button.textContent.trim()))")

        assert js("document.getElementById('secondary-lookup').getBoundingClientRect().x > document.getElementById('primary-lookup').getBoundingClientRect().x")
        QTest.qWait(200)
        window.web.grab().save('/tmp/ukijiten-split-lookups.png')
        js("secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        js("document.getElementById('navbar-hide').click()")
        wait_until(lambda:window.settings['navbar_auto_hide'])
        assert floating.load_settings()['navbar_auto_hide'] and floating.load_settings()['lookup_split']
        search_y=js("document.querySelector('.searchbar').getBoundingClientRect().y")
        js("navbar.dispatchEvent(new PointerEvent('pointerleave'))")
        QTest.qWait(400)
        assert not js("panel.classList.contains('navbar-hidden')")
        js("navbar.dispatchEvent(new PointerEvent('pointerenter'))")
        QTest.qWait(500)
        assert not js("panel.classList.contains('navbar-hidden')")
        js("navbar.dispatchEvent(new PointerEvent('pointerleave'))")
        wait_until(lambda:js("panel.classList.contains('navbar-hidden')"),seconds=2)
        wait_until(lambda:js("getComputedStyle(navbar).opacity")=='0')
        assert js("getComputedStyle(navbar).display")!='none'
        hidden_search_y=js("document.querySelector('.searchbar').getBoundingClientRect().y")
        assert hidden_search_y<search_y-5
        # Crossing the lower search field must not reveal navigation.
        js("panel.dispatchEvent(new PointerEvent('pointermove',{clientY:document.querySelector('.searchbar').getBoundingClientRect().bottom,pointerType:'mouse',bubbles:true}));panel.dispatchEvent(new PointerEvent('pointermove',{clientY:panel.getBoundingClientRect().top+navbarRevealStart+2,pointerType:'mouse',bubbles:true}))")
        QTest.qWait(200)
        assert js("getComputedStyle(navbar).opacity")=='0'
        # Reveal begins near the magnifier's ink, below the search field's top edge.
        assert js("panel.getBoundingClientRect().top+navbarRevealStart>document.querySelector('.searchbar').getBoundingClientRect().top+5")
        # One crossing starts the whole reveal, even if the pointer then stops.
        js("panel.dispatchEvent(new PointerEvent('pointermove',{clientY:panel.getBoundingClientRect().top+navbarRevealStart-1,pointerType:'mouse',bubbles:true}))")
        wait_until(lambda:js("getComputedStyle(navbar).opacity")=='1')
        assert abs(js("document.querySelector('.searchbar').getBoundingClientRect().y")-search_y)<1
        # Move down onto the projector without relying on a native hover-entry event.
        js("(()=>{const r=document.getElementById('pane-stay-visible').getBoundingClientRect();panel.dispatchEvent(new PointerEvent('pointermove',{clientX:r.left+r.width/2,clientY:r.top+r.height/2,pointerType:'mouse',bubbles:true}));})()")
        QTest.qWait(900)
        assert js("getComputedStyle(navbar).opacity")=='1'
        # A layout-generated leave while still over a control must not hide it.
        js("(()=>{const r=document.getElementById('pane-stay-visible').getBoundingClientRect();navbar.dispatchEvent(new PointerEvent('pointerleave',{clientX:r.left+r.width/2,clientY:r.top+r.height/2,pointerType:'mouse'}));})()")
        QTest.qWait(900)
        assert js("getComputedStyle(navbar).opacity")=='1'
        js("panel.dispatchEvent(new PointerEvent('pointermove',{clientY:document.querySelector('.searchbar').getBoundingClientRect().bottom,pointerType:'mouse',bubbles:true}))")
        QTest.qWait(400)
        assert js("getComputedStyle(navbar).opacity")=='1'
        wait_until(lambda:js("getComputedStyle(navbar).opacity")=='0')
        js("document.getElementById('navbar-hide').click();resetLookupGrid();setWindowActive(false)")
        wait_until(lambda:not window.settings['lookup_split'] and not window.settings['navbar_auto_hide'])
        assert js("document.getElementById('secondary-lookup').hidden")
        js("setWindowActive(true);setQuery('');app.search('')")
        initial_button_color=js("getComputedStyle(document.documentElement).getPropertyValue('--settings-button-bg')")
        js("applyPanelColor('#e5eecc')")
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--settings-button-bg')")!=initial_button_color
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--settings-button-text')").strip()=='#101719'
        js('applyPanelColor(motion.panel_color)')

        wait_until(lambda:js("!!document.getElementById('pane-background')?.complete"))
        wait_until(lambda:window.stats_store.summary()['total']==3)
        js("document.getElementById('reading-stats-button').click()")
        wait_until(lambda:js("!!document.getElementById('reading-stats')"))
        assert js("document.querySelector('.stats-card strong').textContent")=='3'
        assert js("getComputedStyle(document.getElementById('inline-settings')).position")=='absolute'
        assert js("document.querySelectorAll('.stats-heatmap i').length")>=365
        feed_clients[0].sendTextMessage(json.dumps({'event':'text_v2_update','data':{'id':'stats-1','session_id':'test','text':'日本語を読む123','revision':1,'scene':'Test book'}}))
        wait_until(lambda:js("document.querySelector('.stats-card strong').textContent==='6'"))
        # Full history expands saved text, multi-selects lines and deletes only
        # after confirmation through the actual bridge, without feed replay.
        window.stats_store.record('history-ui:1','先生です','History fixture','2026-11-18T12:00:00-06:00')
        window.stats_store.record('history-ui:2','明日です','History fixture','2026-11-18T12:00:20-06:00')
        window.refresh_reading_stats();wait_until(lambda:js("document.querySelector('.stats-card strong').textContent==='14'"))
        js("document.getElementById('stats-history').click()")
        wait_until(lambda:js("!!document.getElementById('history-source')"))
        wait_until(lambda:js("[...document.querySelectorAll('#history-source option')].some(option=>option.value==='History fixture')"))
        js("document.getElementById('history-source').value='History fixture';document.getElementById('history-source').dispatchEvent(new Event('change'))")
        wait_until(lambda:js("document.querySelectorAll('.history-group').length===1&&document.getElementById('history-summary').textContent.startsWith('2 records')"))
        js("document.querySelector('.history-group>summary').click()")
        wait_until(lambda:js("document.querySelectorAll('.history-group .history-entry').length===2"))
        js("document.querySelector('.history-group .history-entry>summary').click()")
        wait_until(lambda:js("document.querySelector('.history-saved-text')?.textContent==='明日です'"))
        window.web.grab().save('/tmp/ukijiten-reading-history.png')
        js("document.querySelectorAll('.history-group .history-entry>summary input').forEach(input=>input.click());window.originalConfirm=window.confirm;window.confirm=()=>false;document.getElementById('history-delete').click()")
        assert window.stats_store.db.execute("SELECT COUNT(*) FROM readings WHERE source='History fixture'").fetchone()[0]==2
        js("window.confirm=()=>true;document.getElementById('history-delete').click()")
        wait_until(lambda:window.stats_store.db.execute("SELECT COUNT(*) FROM readings WHERE source='History fixture'").fetchone()[0]==0)
        wait_until(lambda:js("document.querySelector('#history-results .stats-empty')?.textContent==='No reading records.'"))
        assert not window.stats_store.record('history-ui:1','先生です','History fixture',revision=50)
        js("window.confirm=window.originalConfirm;document.getElementById('history-back').click()")
        wait_until(lambda:js("document.querySelector('.stats-card strong')?.textContent==='6'"))
        # Refresh is an icon-only action and completes through the actual bridge/worker path.
        assert js("!!document.querySelector('#stats-refresh svg')")
        assert js("document.getElementById('stats-refresh').textContent.trim()") == ''
        original_refresh=floating.refresh_configured
        floating.refresh_configured=lambda *args:'Anki updated · Mokuro WebDAV updated'
        js("document.getElementById('stats-refresh').click()")
        wait_until(lambda:window.stats_refresh_future is not None)
        wait_until(lambda:window.stats_refresh_future is None)
        wait_until(lambda:js("document.querySelector('.stats-import-notice').textContent.includes('Mokuro WebDAV updated')"))
        assert not js("document.getElementById('stats-refresh').disabled")
        assert not js("!!document.querySelector('.stats-heading h2')")
        assert window.stats_notice_timer.isActive()
        window.stats_notice_timer.start(50)
        wait_until(lambda:not window.stats_refresh_notice)
        wait_until(lambda:not js("!!document.querySelector('.stats-import-notice')"))
        window.stats_notice_timer.setInterval(5000)
        floating.refresh_configured=original_refresh
        # Source settings stay editable during background updates and save through Qt.
        js("document.getElementById('stats-settings').click()")
        assert js("document.querySelectorAll('.stats-source-setting').length")==9
        assert js("[...document.querySelectorAll('.stats-source-setting')].every(card=>!card.open)")
        assert js("[...document.querySelectorAll('.stats-source-setting > summary input')].every(toggle=>toggle.getBoundingClientRect().width>0)")
        original_capture=window.source_settings.values['gsm']['enabled']
        js("document.querySelector('[data-source=gsm] > summary input').click()")
        assert not js("document.querySelector('[data-source=gsm]').open")
        assert js("statsSettingsDraft.gsm.enabled")!=original_capture
        js("document.querySelector('[data-source=gsm] > summary input').click();document.querySelector('[data-source=gsm] > summary').click()")
        assert js("document.querySelector('[data-source=gsm]').open && document.querySelector('[data-source=gsm] .stats-source-setup').getBoundingClientRect().height>0")
        from mokuro_cloud import connection_update
        cloudconf=root/'mokuro-cloud.conf';cloudconf.write_text('[mokuro_google_drive]\ntype=drive\ntoken={"access_token":"test"}\n')
        connection_update(root,'google_drive',state='connected',account='reader@example.org')
        window.refresh_reading_stats()
        wait_until(lambda:js("document.querySelector('[data-cloud-account=google_drive]').textContent.includes('reader@example.org')"))
        assert js("document.querySelector('[data-cloud-status=google_drive]').textContent")=='Connected'
        assert not js("document.querySelector('[data-cloud-disconnect=google_drive]').hidden")
        js("document.querySelector('[data-cloud-disconnect=google_drive]').click()")
        wait_until(lambda:js("document.querySelector('[data-cloud-status=google_drive]').textContent==='Not connected'"))
        assert 'access_token' not in cloudconf.read_text()
        js("window.savedCloudFixture=structuredClone(readingStats.cloud_connections);window.savedMokuroFixture=structuredClone(statsSettingsDraft.mokuro);statsSettingsDraft.mokuro.enabled=true;statsSettingsDraft.mokuro.onedrive.enabled=false;readingStats.cloud_connections.onedrive={state:'needs_auth',configured:true};renderStatsSourceSettings()")
        assert js("document.querySelector('[data-cloud-status=onedrive]').hidden")
        js("document.querySelector('[data-provider=onedrive] > summary input').click()")
        assert js("!document.querySelector('[data-cloud-status=onedrive]').hidden && document.querySelector('[data-cloud-status=onedrive]').textContent==='Sign-in required'")
        js("readingStats.cloud_connections.onedrive.state='error';updateCloudConnections()")
        assert js("document.querySelector('[data-cloud-status=onedrive]').textContent")=='Could not refresh'
        js("document.querySelector('[data-provider=onedrive] > summary input').click()")
        assert js("document.querySelector('[data-cloud-status=onedrive]').hidden && !document.querySelector('[data-cloud-status=onedrive]').textContent")
        js("readingStats.cloud_connections=savedCloudFixture;statsSettingsDraft.mokuro=savedMokuroFixture;renderStatsSourceSettings()")
        original_decks=floating.available_decks
        floating.available_decks=lambda config:['Book','Book::Subdeck']
        js("document.querySelector('[data-source=anki] input[role=switch]').click();document.getElementById('stats-load-decks').click()")
        wait_until(lambda:js("document.querySelectorAll('#stats-deck-list label').length===2"))
        js("document.querySelector('#stats-deck-list input').click()")
        assert js("statsSettingsDraft.anki.decks.includes('Book')")
        js("document.querySelector('[data-source=anki] input[role=switch]').click()")
        floating.available_decks=original_decks
        window.resize(510,750);app.processEvents()
        assert js("document.getElementById('reading-stats').scrollWidth<=document.getElementById('inline-settings').clientWidth")
        window.web.grab().save('/tmp/floating-stats-source-settings.png')
        assert js("document.querySelector('[data-source=gsm] input[type=text]').value").endswith('/ws/texthooker')
        js("document.querySelector('[data-source=gsm] input[type=text]').value='ws://localhost:55123/ws/texthooker';document.querySelector('[data-source=gsm] input[type=text]').dispatchEvent(new Event('input'))")
        window.refresh_reading_stats();app.processEvents()
        assert js("document.querySelector('[data-source=gsm] input[type=text]').value").startswith('ws://localhost:55123')
        # Saving a disabled source must retain existing ledger entries.
        js("document.querySelector('[data-source=files] input[role=switch]').click();document.querySelector('.stats-source-settings').requestSubmit()")
        wait_until(lambda:not window.source_settings.values['files']['enabled'])
        wait_until(lambda:js("!!document.getElementById('stats-settings')"))
        assert not js("document.getElementById('stats-add').disabled")
        assert not js("!!document.querySelector('[data-source=manual]')")
        js("document.getElementById('stats-settings').click();document.querySelector('[data-source=files] input[role=switch]').click();document.querySelector('.stats-source-settings').requestSubmit()")
        wait_until(lambda:window.source_settings.values['files']['enabled'])
        wait_until(lambda:js("!!document.getElementById('stats-settings')"))
        window.resize(1500,920);app.processEvents();pump_deadline=time.monotonic()+.3
        while time.monotonic()<pump_deadline:app.processEvents();time.sleep(.01)
        window.web.grab().save('/tmp/floating-reading-stats-desktop.png')
        window.resize(510,750);app.processEvents();pump_deadline=time.monotonic()+.3
        while time.monotonic()<pump_deadline:app.processEvents();time.sleep(.01)
        assert js("document.getElementById('reading-stats').scrollWidth<=document.getElementById('inline-settings').clientWidth")
        assert js("(()=>{const buttons=['stats-refresh','stats-settings','stats-add'].map(id=>document.getElementById(id).getBoundingClientRect());const area=document.getElementById('inline-settings').getBoundingClientRect();return buttons.every(r=>r.width>0&&r.right<=area.right)&&buttons[0].right<=buttons[1].left&&buttons[1].right<=buttons[2].left;})()")
        window.web.grab().save('/tmp/floating-reading-stats-phone.png')
        assert not js("!!document.getElementById('stats-import')")
        assert not js("!!document.getElementById('stats-capture')")
        assert js("document.querySelector('.stats-card-streak span').textContent")=='Streak'
        assert js("(()=>{const c=document.querySelector('.stats-card').getBoundingClientRect(),t=document.querySelector('.stats-card-total').getBoundingClientRect();return Math.abs(c.x-t.x)<2 && t.y>c.y;})()")
        js("document.getElementById('stats-settings').click();document.querySelector('[data-source=gsm] input[role=switch]').click();document.querySelector('.stats-source-settings').requestSubmit()")
        wait_until(lambda:not window.stats_store.preference('capture',True))
        assert window.stats_feed.status=='Paused'
        history=root/'history.csv'
        history.write_text('Date,Log Name,Language,Characters,Duration\n2026-11-01,Imported book,Japanese,100,5\n')
        original_picker=floating.QFileDialog.getOpenFileNames
        floating.QFileDialog.getOpenFileNames=lambda *args:([str(history)],'')
        js("document.getElementById('stats-settings').click();document.getElementById('stats-source-import').click()")
        wait_until(lambda:window.stats_import_future is not None)
        wait_until(lambda:window.stats_import_future is None)
        wait_until(lambda:js("readingStats.total===106"))
        js("document.querySelector('.stats-top button').click()")
        wait_until(lambda:js("document.querySelector('.stats-card strong').textContent==='106'"))
        assert window.stats_store.summary()['seconds']==300
        assert 'Imported 1 record' in js("document.querySelector('.stats-import-notice').textContent")
        floating.QFileDialog.getOpenFileNames=original_picker
        js("document.getElementById('stats-settings').click()")
        assert js("document.querySelector('[data-asset-source=files]').textContent.includes('history.csv')")
        assert not js("document.querySelector('.stats-source-settings').textContent.includes('Mangaseedbox')")
        assert js("document.querySelectorAll('[data-source=mokuro] details.mokuro-provider').length")==5
        js("document.querySelector('[data-source=mokuro] input[role=switch]').click();document.querySelector('[data-provider=webdav]').open=true")
        assert js("document.querySelector('[data-provider=webdav]').textContent.includes('WebDAV URL')")
        js("document.querySelector('[data-source=mokuro]').open=true")
        # WebDAV can save its own connection, retaining the open cards and
        # leaving unrelated edits in this form unsaved.
        saved_gsm_url=window.source_settings.values['gsm']['url']
        js("statsSettingsDraft.gsm.url='ws://unsaved.example:55000/ws/texthooker';const dav=document.querySelector('[data-provider=webdav]');const fields=dav.querySelectorAll('.stats-source-field input');for(const [index,value] of [[0,'https://reader.example'],[1,'reader'],[2,'first-password']]){fields[index].value=value;fields[index].dispatchEvent(new Event('input'));}document.getElementById('stats-webdav-save').click()")
        wait_until(lambda:window.source_settings.values['mokuro']['webdav']['webdav_password']=='first-password')
        wait_until(lambda:js("document.getElementById('stats-webdav-status').textContent.includes('Connection saved')"))
        assert window.source_settings.values['gsm']['url']==saved_gsm_url
        assert js("statsSettingsDraft.gsm.url")=='ws://unsaved.example:55000/ws/texthooker'
        assert js("document.querySelector('[data-source=mokuro]').open && document.querySelector('[data-provider=webdav]').open")
        assert js("document.getElementById('stats-webdav-save').textContent")=='Save connection'
        js("const password=document.querySelector('[data-provider=webdav] input[type=password]');password.value='changed-password';password.dispatchEvent(new Event('input'));document.getElementById('stats-webdav-save').click()")
        wait_until(lambda:window.source_settings.values['mokuro']['webdav']['webdav_password']=='changed-password')
        wait_until(lambda:js("document.getElementById('stats-webdav-status').textContent.includes('Connection saved')"))
        assert 'webdav_password' not in window.source_settings.public()['mokuro']['webdav']
        # Leave no enabled network provider for later fixture refreshes.
        result=json.loads(window.bridge.stats_cloud_disconnect('webdav'))
        assert not result.get('error')
        js("statsSettingsDraft.mokuro.webdav=JSON.parse("+json.dumps(json.dumps(result['settings']['mokuro']['webdav']))+");statsSettingsDraft.gsm.url="+json.dumps(saved_gsm_url)+";renderStatsSourceSettings()")
        window.web.grab().save('/tmp/floating-mokuro-settings.png')
        js("document.querySelector('[data-asset-source=files] button').click()")
        wait_until(lambda:window.stats_store.summary()['total']==6)
        wait_until(lambda:not js("document.querySelector('[data-asset-source=files]').textContent.includes('history.csv')"))
        # Reimport the same file to keep the later dashboard fixture unchanged.
        store=floating.ReadingStats(root/'reading-stats.sqlite3')
        floating.import_path(store,history);store.db.close()
        js('closeSettings()');window.resize(990,670)

        assert js("document.getElementById('settings') !== null")
        window.open_settings()
        assert js("!!document.getElementById('inline-settings')")
        assert js("document.querySelector('[data-background-fade]').disabled")
        assert js("[...document.querySelectorAll('#inline-settings .settings-preview-group > .settings-section')].every(section=>!section.open)")
        assert not js("!!document.getElementById('image-pane-options')")
        assert js("document.querySelectorAll('.image-picker-control').length")==4
        js('applyLookupLayout();applyPreferences(motion)')
        assert js("[...document.querySelectorAll('.image-picker-control')].every(group=>group.children.length===3&&group.querySelector('.image-visibility svg'))")
        assert js("[...document.querySelectorAll('.settings-preview-group')].every(group=>group.children[1].getBoundingClientRect().height>0)")
        # Image visibility follows each pane and its related settings pages.
        assert js("document.querySelectorAll('.background-pane-options input:not(.settings-preview-ghost *)').length")==5
        js("document.getElementById('background-settings').open=true;document.querySelector('input[data-background-pane=settings]').click()")
        wait_until(lambda:window.settings['background_show_settings'] is False)
        wait_until(lambda:js("panel.dataset.backgroundPane==='settings'&&getComputedStyle(document.getElementById('pane-background')).visibility==='hidden'"))
        js('closeSettings()')
        wait_until(lambda:js("panel.dataset.backgroundPane==='dictionary'&&getComputedStyle(document.getElementById('pane-background')).visibility==='visible'"))
        for group,open_pane in [('dictionary',window.open_manager),('popup',window.open_popup_settings),('stats',window.open_reading_stats),('translation',window.open_translation)]:
            window.update_preference('background_show_'+group,False);open_pane()
            wait_until(lambda group=group:js('panel.dataset.backgroundPane')==group and js("panel.classList.contains('background-image-disabled')"))
            if group=='stats':
                js("document.getElementById('stats-settings').click()")
                assert js("panel.dataset.backgroundPane==='stats'&&panel.classList.contains('background-image-disabled')")
            window.update_preference('background_show_'+group,True)
            wait_until(lambda:not js("panel.classList.contains('background-image-disabled')"))
            js('closeSettings()')
        window.update_preference('background_show_settings',True);window.open_settings()
        wait_until(lambda:js("panel.dataset.backgroundPane==='settings'&&!panel.classList.contains('background-image-disabled')"))
        assert all(floating.load_settings()['background_show_'+group] for group in ('dictionary','popup','stats','translation','settings'))
        # Independent image blur and edge pairs for selectively rounded corners.
        js("document.getElementById('avatar-settings').open=true;document.getElementById('background-settings').open=true")
        for key in ('avatar_image_blur','dictionary_image_blur'):
            js("(()=>{const input=document.querySelector('[data-setting="+key+"] input');input.value=8;input.dispatchEvent(new Event('input'));})()")
            wait_until(lambda key=key:window.settings[key]==8)
        assert js("getComputedStyle(document.getElementById('pane-background')).filter")=='blur(8px) opacity(1)'
        js("const imageOpacity=document.querySelector('[data-setting=dictionary_image_opacity] input');imageOpacity.value=45;imageOpacity.dispatchEvent(new Event('input'))")
        wait_until(lambda:window.settings['dictionary_image_opacity']==45)
        assert floating.load_settings()['dictionary_image_opacity']==45
        assert js("getComputedStyle(document.getElementById('pane-background')).filter")=='blur(8px) opacity(0.45)'
        js("const radius=document.querySelector('[aria-label=\"dictionary corner radius\"]');radius.value=0;radius.dispatchEvent(new Event('input'))")
        wait_until(lambda:js("getComputedStyle(panel).borderRadius")=='0px')
        assert js("document.querySelector('[aria-label=\"dictionary round top\"]').getAttribute('aria-pressed')")=='true'
        assert js("document.querySelector('[aria-label=\"dictionary round bottom\"]').getAttribute('aria-pressed')")=='true'
        js("document.querySelector('[aria-label=\"dictionary round left\"]').click()")
        wait_until(lambda:window.settings['dictionary_corner_mode']=='left')
        assert js("document.querySelector('[aria-label=\"dictionary round top\"]').getAttribute('aria-pressed')")=='false'
        js("document.querySelector('[aria-label=\"dictionary round right\"]').click()")
        wait_until(lambda:window.settings['dictionary_corner_mode']=='sides')
        js("document.querySelector('[aria-label=\"dictionary round bottom\"]').click()")
        wait_until(lambda:window.settings['dictionary_corner_mode']=='bottom')
        assert js("document.querySelector('[aria-label=\"dictionary round left\"]').getAttribute('aria-pressed')")=='false'
        assert js("[...document.querySelectorAll('.background-pane-options input,.pane-corner-controls input[type=checkbox]')].every(input=>getComputedStyle(input,'::after').content==='none')")
        assert js("(()=>{const clear=document.querySelector('.settings-clear-color').getBoundingClientRect(),color=document.querySelector('[data-setting=avatar_background_color] input').getBoundingClientRect();return clear.right<color.left&&Math.abs((clear.top+clear.bottom)-(color.top+color.bottom))<2;})()")
        js("document.querySelector('[aria-label=\"Make avatar background transparent\"]').click();document.querySelector('[data-setting=avatar_background_color] input').click()")
        wait_until(lambda:window.color_dialog is not None)
        window.color_dialog.setCurrentColor(QColor('#89abcd'))
        wait_until(lambda:window.settings['avatar_background_color']=='#89abcd')
        window.color_dialog.reject()
        wait_until(lambda:window.color_dialog is None)
        assert window.settings['avatar_background_color']==''
        for key,value in [('avatar_image_blur',0),('dictionary_image_blur',0),('dictionary_image_opacity',100),('dictionary_corner_radius',23),('dictionary_corner_mode','all')]:window.update_preference(key,value)
        js("document.getElementById('avatar-settings').open=false;document.getElementById('background-settings').open=false")
        js("document.querySelector('[data-section=main-entry-text-size] > summary').click()")
        assert js("document.querySelector('[data-section=main-entry-text-size]').open")
        wait_until(lambda:window.popup_config.values['section_states'].get('main-entry-text-size') is True)
        assert json.loads((root/'popup-settings.json').read_text())['section_states']['main-entry-text-size'] is True

        assert js("getComputedStyle(document.querySelector('[data-setting=font_headword] input')).fontSize")=='13px'
        assert js("document.querySelector('[data-setting=font_headword] input').getBoundingClientRect().height")<=32
        assert js("getComputedStyle(document.querySelector('[data-setting=font_headword] input')).backgroundColor")=='rgba(0, 0, 0, 0)'

        js("document.querySelector('[data-section=main-entry-text-size] > summary').click()")

        js("document.querySelector('#background-settings > summary').click();const fadeToggle=document.querySelector('[data-setting=background_crossfade] input');fadeToggle.click()")
        wait_until(lambda:window.settings['background_crossfade'])
        wait_until(lambda:not js("document.querySelector('[data-background-fade]').disabled"))
        js("const fadeDuration=document.querySelector('[data-background-fade]');fadeDuration.value='800';fadeDuration.dispatchEvent(new Event('input'))")
        wait_until(lambda:window.settings['background_fade_ms']==800)
        assert floating.load_settings()['background_crossfade']
        assert floating.load_settings()['background_fade_ms']==800
        js("const color=document.querySelector('[data-setting=panel_color] input');color.value='#234567';color.dispatchEvent(new Event('input'))")
        wait_until(lambda:window.settings['panel_color']=='#234567')
        wait_until(lambda:floating.load_settings()['panel_color']=='#234567')
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--panel-color-rgb').trim()")=='35,69,103'
        # Text color modes persist, follow previews, and recalculate on Automatic.
        assert window.settings['text_color_mode']=='automatic'
        assert js("document.querySelector('[data-setting=text_color_mode]').nextElementSibling.dataset.setting")=='panel_color'
        assert js("[...document.querySelector('[data-setting=text_color_mode] select').options].map(option=>option.textContent).join(',')")=='Automatic,Black,White'
        contrast_darkness=window.settings['panel_darkness']
        window.update_preference('panel_darkness',100)
        wait_until(lambda:js('motion.panel_darkness')==100)
        js("document.querySelector('[data-setting=panel_color] input').click()")
        wait_until(lambda:window.color_dialog is not None)
        window.color_dialog.setCurrentColor(QColor('#ffffff'))
        wait_until(lambda:js("document.documentElement.dataset.contrastScheme==='light'"))
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")=='#17202a'
        window.color_dialog.reject()
        wait_until(lambda:window.color_dialog is None and js("document.documentElement.dataset.contrastScheme==='dark'"))
        def text_mode(mode):
            js("(()=>{const selector=document.querySelector('[data-setting=text_color_mode] select');selector.value="+json.dumps(mode)+";selector.dispatchEvent(new Event('input'));})()")
            wait_until(lambda:window.settings['text_color_mode']==mode and floating.load_settings()['text_color_mode']==mode)
        text_mode('white')
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")=='#ffffff'
        js("document.querySelector('[data-setting=panel_color] input').click()")
        wait_until(lambda:window.color_dialog is not None)
        window.color_dialog.setCurrentColor(QColor('#ffffff'))
        wait_until(lambda:js("motion.panel_color==='#ffffff'"))
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")=='#ffffff'
        window.color_dialog.reject()
        wait_until(lambda:window.color_dialog is None)
        text_mode('black')
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")=='#000000'
        window.update_preference('panel_color','#ffffff')
        wait_until(lambda:js("motion.panel_color==='#ffffff'"))
        text_mode('white')
        text_mode('automatic')
        wait_until(lambda:js("document.documentElement.dataset.contrastScheme==='light'"))
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")=='#17202a'
        window.update_preference('panel_color','#234567')
        wait_until(lambda:js("document.documentElement.dataset.contrastScheme==='dark'"))
        window.update_preference('panel_darkness',contrast_darkness)
        wait_until(lambda:js('motion.panel_darkness')==contrast_darkness)
        # Non-modal color selection previews during dragging and restores fade on close.
        saved_fade=window.settings['auto_fade'];window.focus_timer.stop()
        js("document.querySelector('[data-setting=panel_color] input').click()")
        wait_until(lambda:window.color_dialog is not None)
        assert window.color_dialog.windowModality()==Qt.WindowModality.NonModal
        window.color_dialog.setCurrentColor(QColor('#8ab2cd'))
        wait_until(lambda:js("getComputedStyle(document.documentElement).getPropertyValue('--panel-color-rgb').trim()")=='138,178,205')
        wait_until(lambda:floating.load_settings()['panel_color']=='#234567')
        js('motion.auto_fade=true;motion.fade_delay_ms=50;imageHovered=false;panelHovered=false;nativePanelHovered=false;setWindowActive(false);scheduleFade()')
        QTest.qWait(180)
        assert js("colorPreviewOpen&&!panel.classList.contains('faded')")
        window.color_dialog.reject()
        wait_until(lambda:window.color_dialog is None and not js('colorPreviewOpen'))
        assert window.settings['panel_color']=='#234567' and window.settings['auto_fade']==saved_fade
        wait_until(lambda:floating.load_settings()['panel_color']=='#234567')
        js('motion.auto_fade=true;motion.fade_delay_ms=50;motion.fade_out_ms=0;imageHovered=false;panelHovered=false;nativePanelHovered=false;setWindowActive(false);scheduleFade()')
        wait_until(lambda:js("panel.classList.contains('faded')"))
        js('applyPreferences('+json.dumps(window.settings)+');setWindowActive(true);showPanel()')
        js("document.querySelector('[data-setting=panel_color] input').click()")
        wait_until(lambda:window.color_dialog is not None)
        window.color_dialog.setCurrentColor(QColor('#456789'));window.color_dialog.accept()
        wait_until(lambda:floating.load_settings()['panel_color']=='#456789' and not js('colorPreviewOpen'))
        window.update_preference('panel_color','#234567');window.focus_timer.start()
        js("document.querySelector('[data-setting=background_fade_ms]').scrollIntoView({block:'center'})")
        window.web.grab().save('/tmp/floating-background-crossfade.png')
        window.background_timer.stop()
        second=root/'second.png'
        image=QImage(4,4,QImage.Format.Format_RGB32);image.fill(QColor('red'));image.save(str(second))
        window.update_preference('blur_px',1)
        wait_until(lambda:js("document.querySelector('[data-setting=blur_px] input').checked"))
        window.set_background(str(second))
        assert window.settings['blur_px']==0
        wait_until(lambda:not js("document.querySelector('[data-setting=blur_px] input').checked"))
        wait_until(lambda:js("document.querySelectorAll('.pane-background-layer').length===2"))
        assert js("document.getElementById('pane-background').getAnimations()[0].effect.getTiming().duration")==800
        assert js("document.querySelector('.pane-background-previous').nextElementSibling.id==='pane-background'")
        wait_until(lambda:js("!document.querySelector('.pane-background-previous')"))
        assert js("document.getElementById('pane-background').style.opacity")=='1'
        sizes=window.splitter.sizes()
        window.update_preference('avatar_seconds',4)
        assert window.avatar_timer.interval()==4000
        window.open_native_manager()
        app.processEvents()
        assert window.dictionary_overlay.isVisible()
        assert window.manager_background.tint.name()=='#234567'
        assert window.manager.dictionary_list.count()==3
        # Checkbox clicks apply immediately, including on a row that is not selected.
        dictionaries=window.manager.dictionary_list
        original_enabled=dict(window.manager.db.execute('SELECT id,enabled FROM dictionaries'))
        item=dictionaries.item(0)
        did=item.data(Qt.ItemDataRole.UserRole)
        option=QStyleOptionViewItem();option.initFrom(dictionaries)
        option.rect=dictionaries.visualItemRect(item);option.widget=dictionaries
        dictionaries.itemDelegate().initStyleOption(option,dictionaries.indexFromItem(item))
        checkbox=dictionaries.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator,option,dictionaries)
        assert not checkbox.isEmpty()
        for enabled in [not bool(original_enabled[did]),bool(original_enabled[did])]:
            QTest.mouseClick(dictionaries.viewport(),Qt.MouseButton.LeftButton,pos=checkbox.center())
            assert window.db.execute('SELECT enabled FROM dictionaries WHERE id=?',(did,)).fetchone()[0]==int(enabled)
        assert window.manager.select_all_button.menu() is None
        window.manager.select_all_button.click()
        assert all(value for _,value in window.manager.db.execute('SELECT id,enabled FROM dictionaries'))
        window.manager.unselect_all_button.click()
        assert not any(value for _,value in window.manager.db.execute('SELECT id,enabled FROM dictionaries'))
        # Modifier clicks still select only one row, for reorder/removal.
        for index,modifier in [(0,Qt.KeyboardModifier.NoModifier),(1,Qt.KeyboardModifier.ControlModifier),(2,Qt.KeyboardModifier.ShiftModifier)]:
            QTest.mouseClick(dictionaries.viewport(),Qt.MouseButton.LeftButton,modifier,pos=dictionaries.visualItemRect(dictionaries.item(index)).center())
            assert len(dictionaries.selectedItems())==1
        for index in range(dictionaries.count()):
            item=dictionaries.item(index)
            item.setCheckState(Qt.CheckState.Checked if original_enabled[item.data(Qt.ItemDataRole.UserRole)] else Qt.CheckState.Unchecked)
        assert dict(window.manager.db.execute('SELECT id,enabled FROM dictionaries'))==original_enabled
        assert window.manager_background.size()==window.dictionary_overlay.size()
        # Hovering the native manager keeps it visible without window activation.
        # A pointerleave from the WebEngine pane underneath must not override it.
        window.focus_timer.stop()
        original_fade_out=window.settings['fade_out_ms']
        window.settings['fade_out_ms']=0
        js('motion.auto_fade=true;motion.fade_delay_ms=40;motion.fade_out_ms=0;fadePaused=true;imageHovered=false;panelHovered=false;setWindowActive(false);showPanel()')
        QApplication.sendEvent(window.dictionary_overlay,QEnterEvent(QPointF(20,20),QPointF(20,20),QPointF(window.dictionary_overlay.mapToGlobal(window.dictionary_overlay.rect().center()))))
        wait_until(lambda:js('nativePanelHovered'))
        js("resumeFade();panel.dispatchEvent(new PointerEvent('pointerleave'))")
        QTest.qWait(160)
        assert not js('windowActive')
        assert window.panel_visible and window.dictionary_overlay.isVisible()
        assert not js("panel.classList.contains('faded')")
        QApplication.sendEvent(window.dictionary_overlay,QEvent(QEvent.Type.Leave))
        wait_until(lambda:not window.panel_visible and not window.dictionary_overlay.isVisible())
        # Keeping the pointer on the avatar also survives losing keyboard focus.
        js('avatarHover(true);setWindowActive(false)')
        QTest.qWait(160)
        assert window.panel_visible
        js('avatarHover(false)')
        wait_until(lambda:not window.panel_visible)
        window.settings['fade_out_ms']=original_fade_out
        js('motion.auto_fade=false;setWindowActive(true);dictionaryHover(false)')
        wait_until(lambda:window.panel_visible and window.dictionary_overlay.isVisible())
        window.focus_timer.start()
        assert all(abs(a-b)<3 for a,b in zip(sizes,window.splitter.sizes()))
        window.set_background(str(gif))
        assert window.manager_background.transition.duration()==800
        assert not window.manager_background.previous_frame.isNull()
        assert window.manager_background.fade_progress<1
        wait_until(lambda:window.manager_background.previous_frame.isNull())
        assert window.manager_background.fade_progress==1
        window.set_background(str(second))
        assert not window.manager_background.previous_frame.isNull()
        window.update_preference('background_crossfade',False)
        assert window.manager_background.previous_frame.isNull()
        wait_until(lambda:js("!document.querySelector('.pane-background-previous')"))
        window.set_background(str(gif))
        wait_until(lambda:js("document.getElementById('pane-background').dataset.source.endsWith('background.gif')"))
        assert js("document.getElementById('pane-background').getAnimations().length")==0
        assert js("getComputedStyle(document.getElementById('pane-background')).visibility")=='hidden'
        # Drain initial hover/activation notifications before forcing fade state.
        js('clearTimeout(fadeTimer); panelHovered=false; imageHovered=false;')
        for _ in range(15):app.processEvents();time.sleep(.01)
        window.settings['fade_out_ms']=0
        window.panel_visible=False
        window.fade_dictionary_overlay(False)
        window.finish_dictionary_fade()
        assert not window.dictionary_overlay.isVisible()
        window.panel_visible=True
        window.fade_dictionary_overlay(True)
        assert window.dictionary_overlay.isVisible()
        window.close_dictionary_manager()
        assert not window.dictionary_overlay.isVisible()
        for _ in range(4):window.rotate_panes();app.processEvents()
        js("setQuery('先生')")
        window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        wait_until(lambda:bool(js("!!document.querySelector('.entry')")))
        assert not window.dictionary_overlay.isVisible()
        assert js("!document.getElementById('inline-settings')")
        # Exercise real DOM input events and the QWebChannel debounce/IME path.
        requests=[]
        original_submit=window.lookup_worker.submit
        def record_submit(query):
            requests.append(query);original_submit(query)
        window.lookup_worker.submit=record_submit
        js("query.value='先'; query.dispatchEvent(new Event('input')); query.value='先生'; query.dispatchEvent(new Event('input'));")
        wait_until(lambda:bool(requests))
        assert requests==['先生'],requests
        def pump_for(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:app.processEvents();time.sleep(.005)
        requests.clear()
        js("query.dispatchEvent(new CompositionEvent('compositionstart')); query.value='せ'; query.dispatchEvent(new InputEvent('input',{isComposing:true}));")
        pump_for(.25)
        assert requests==[]
        js("query.value='先生'; query.dispatchEvent(new CompositionEvent('compositionend'))")
        wait_until(lambda:bool(requests))
        assert requests==['先生']
        requests.clear()
        js("query.value='先?'; query.dispatchEvent(new Event('input'))")
        pump_for(.25)
        assert requests==[]
        js("query.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
        wait_until(lambda:bool(requests))
        assert requests==['先?']
        payload=json.dumps([{'text':'先生','length':2}])
        window.hover_position=window.web.mapToGlobal(window.web.rect().bottomRight())
        window.hover_worker.submit(payload)
        wait_until(lambda:window.hover_popup is not None and window.hover_popup.isVisible())
        assert window.hover_popup.isWindow()
        window.hide_hover_popup()
        assert not window.hover_popup.isVisible()
        window.update_preference('background_crossfade',True)
        window.set_background(str(second))
        wait_until(lambda:js("!!document.querySelector('.pane-background-previous')"))
        # Removing a source mid-transition must clear both layers and cancel the pending fade.
        window.bridge.remove_background()
        assert window.settings['background_folder']==''
        assert window.settings['background_image']==''
        assert not window.background_timer.isActive()
        assert js("document.getElementById('pane-background').hidden")
        assert js("document.querySelectorAll('.pane-background-previous').length")==0
        window.open_popup_settings()
        assert js("document.querySelector('#inline-settings h2').textContent")=='Popup settings'
        assert js("getComputedStyle(document.getElementById('inline-settings')).position")=='absolute'
        assert js("getComputedStyle(document.querySelector('#inline-settings button')).backgroundColor")=='rgba(0, 0, 0, 0)'
        assert not js("!!document.querySelector('[data-section=popup-dictionaries]')")
        window.web.grab().save('/tmp/native-popup-settings.png')
        assert js("getComputedStyle(document.getElementById('popup-dictionary-list')).display")!='none'
        assert js("document.getElementById('popup-dictionary-list').closest('details')===null")
        original_order=window.db.execute('SELECT id,sort_order,enabled FROM dictionaries ORDER BY id').fetchall()
        expected=window.popup_config.values['dictionary_order'][1]
        js("document.querySelector('.popup-order-buttons button:last-child').click()")
        wait_until(lambda:window.popup_config.values['dictionary_order'][0]==expected)
        assert window.db.execute('SELECT id,sort_order,enabled FROM dictionaries ORDER BY id').fetchall()==original_order
        js("document.getElementById('popup-hotkey-record').click();document.dispatchEvent(new MouseEvent('mousedown',{button:2,buttons:2,bubbles:true}))")
        wait_until(lambda:window.popup_config.values['scan_hotkey']==['Mouse2'])
        assert 'Right mouse' in js("document.getElementById('popup-hotkey-record').textContent")
        js("document.getElementById('popup-hotkey-record').click();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Control',code:'ControlLeft',ctrlKey:true,bubbles:true}));document.dispatchEvent(new KeyboardEvent('keydown',{key:'d',code:'KeyD',ctrlKey:true,bubbles:true}));")
        wait_until(lambda:window.popup_config.values['scan_hotkey']==['Control','KeyD'])
        assert not js('scanHotkeyListening')
        js("closeSettings()")
        window.popup_config.update('scan_hotkey',['Mouse2'])
        window.web.page().runJavaScript('setPopupPreferences('+json.dumps(window.popup_config.values)+')')
        js("renderResults('<article class=entry><h3>先生</h3><p>先生</p></article>')")
        js("(()=>{const e=document.querySelector('.entry h3');const r=e.getBoundingClientRect();e.dispatchEvent(new PointerEvent('pointerdown',{clientX:r.left+2,clientY:r.top+r.height/2,button:2,buttons:2,pointerType:'mouse',bubbles:true}));})()")
        wait_until(lambda:window.hover_popup.isVisible())
        assert window.hover_popup.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        popup_identity=id(window.hover_popup)
        window.bridge.hover_lookup(json.dumps([{'text':'先制','length':2}]),80,80)
        wait_until(lambda:window.hover_worker.pending is None)
        assert id(window.hover_popup)==popup_identity and window.hover_popup.isVisible()
        popup_text=[]
        window.hover_popup.page().runJavaScript('document.getElementById("content").innerText',lambda value:popup_text.append(value))
        wait_until(lambda:bool(popup_text))
        assert '先制' in popup_text[0],popup_text
        window.hover_popup.grab().save('/tmp/native-popup.png')
        # Keep updating while the forward mouse button stays held, even across blur.
        window.popup_config.update('scan_hotkey',['Mouse4'])
        window.web.page().runJavaScript('setPopupPreferences('+json.dumps(window.popup_config.values)+')')
        js("renderResults('<article class=entry><h3>先生</h3></article><article class=entry><h3>先制</h3></article>')")
        js("(()=>{const e=document.querySelectorAll('.entry h3')[0],r=e.getBoundingClientRect();e.dispatchEvent(new PointerEvent('pointerdown',{clientX:r.left+2,clientY:r.top+r.height/2,button:4,buttons:16,pointerType:'mouse',bubbles:true}));})()")
        wait_until(lambda:'先生' in window.popup_markup)
        js("window.dispatchEvent(new Event('blur'));(()=>{const e=document.querySelectorAll('.entry h3')[1],r=e.getBoundingClientRect();e.dispatchEvent(new PointerEvent('pointermove',{clientX:r.left+2,clientY:r.top+r.height/2,buttons:16,pointerType:'mouse',bubbles:true}));})()")
        wait_until(lambda:'先制' in window.popup_markup)
        assert id(window.hover_popup)==popup_identity
        # Both halves of a glyph must start at that glyph, not the next caret.
        window.hide_hover_popup()
        pump_for(.1)
        scan_requests=[]
        original_hover_submit=window.hover_worker.submit
        window.hover_worker.submit=lambda payload:scan_requests.append(json.loads(payload))
        for markup in ['一二三','<span>一</span><span>二三</span>','𠮷二三']:
            js("renderResults("+json.dumps('<article class=entry><h3>'+markup+'</h3></article>')+")")
            expected='𠮷二三' if '𠮷' in markup else '一二三'
            for fraction in [.2,.75,.95]:
                scan_requests.clear()
                js("window.resetPopupScan();(()=>{const e=document.querySelector('.entry h3'),n=e.firstChild.nodeType===3?e.firstChild:e.firstChild.firstChild;const r=document.createRange();r.setStart(n,0);r.setEnd(n,n.data.codePointAt(0)>65535?2:1);const b=r.getBoundingClientRect();e.dispatchEvent(new PointerEvent('pointermove',{clientX:b.left+b.width*"+str(fraction)+",clientY:b.top+b.height/2,buttons:16,pointerType:'mouse',bubbles:true}));})()")
                wait_until(lambda:bool(scan_requests))
                assert scan_requests[0][0]['text']==expected,scan_requests
        window.hover_worker.submit=original_hover_submit
        # Real Qt outside-click event must immediately dismiss the popup.
        from PySide6.QtTest import QTest
        QTest.mouseClick(window.avatar,Qt.MouseButton.LeftButton)
        assert not window.hover_popup.isVisible()
        window.open_popup_settings()
        assert not window.hover_popup.isVisible()
        assert not hasattr(window,'full_yomitan')
        # Native controls must stay below active resize edges.
        window.open_native_manager();window.update_resize_edges()
        assert len(window.resize_edges)==8
        # The shortcut's prompt belongs to this process, and Enter returns focus to lookup.
        window.open_settings()
        window.settings.update(auto_fade=True, fade_delay_ms=100, fade_out_ms=0)
        js("Object.assign(motion,{auto_fade:true,fade_delay_ms:100,fade_out_ms:0}); panelHovered=false; imageHovered=false")
        shortcut_client=subprocess.Popen([sys.executable,'-c',
            f"import sys;sys.path.insert(0,{str(floating.ROOT)!r});import floating_dictionary as f;f.SOCKET_NAME={floating.SOCKET_NAME!r};sys.exit(f.main(['--popup']))"],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        wait_until(lambda:window.lookup_prompt is not None)
        wait_until(lambda:shortcut_client.poll() is not None)
        assert shortcut_client.returncode==0,shortcut_client.stderr.read().decode()
        prompt=window.lookup_prompt
        assert prompt.parentWidget() is window
        assert floating.send_to_instance('',prompt=True)
        pump_for(.1)
        assert window.lookup_prompt is prompt
        prompt.setTextValue('先生')
        prompt.accept()
        wait_until(lambda:window.lookup_prompt is None and window.isActiveWindow())
        wait_until(lambda:js("windowActive && document.activeElement===query && query.value==='先生'"))
        pump_for(.4)
        assert window.panel_visible
        assert not js("panel.classList.contains('faded')")
        assert not js("!!document.getElementById('inline-settings')")
        # A real focus change still allows the configured fade after clicking away.
        outside=QWidget();outside.resize(100,100);outside.show();outside.raise_();outside.activateWindow()
        QTest.mouseClick(outside,Qt.MouseButton.LeftButton)
        wait_until(lambda:outside.isActiveWindow())
        js('panelHovered=false; imageHovered=false; scheduleFade()')
        wait_until(lambda:not window.panel_visible)
        outside.close()
        window.show_and_raise()
        wait_until(lambda:window.isActiveWindow())
        # Cancel also restores the dictionary without losing the previous query.
        window.open_lookup_prompt()
        window.lookup_prompt.reject()
        wait_until(lambda:window.isActiveWindow() and window.lookup_prompt is None)
        assert window.query=='先生'
        # Reading and Anki heatmaps have distinct activity data and independent year controls.
        with window.stats_store.db:
            window.stats_store.db.execute("INSERT OR REPLACE INTO anki_daily VALUES ('2020-11-12',42000,7)")
            window.stats_store.db.execute("INSERT OR REPLACE INTO anki_deck_totals VALUES ('Kaishi 1.5k',12000,2)")
            window.stats_store.db.execute("INSERT OR REPLACE INTO anki_deck_totals VALUES ('Mining',30000,5)")
        window.open_reading_stats()
        wait_until(lambda:js("!!document.getElementById('anki-consistency')"))
        assert js("document.getElementById('anki-time-summary').nextElementSibling.id")=='anki-consistency'
        assert js("document.getElementById('reading-consistency').textContent.includes('active')")
        assert js("[...document.querySelector('#anki-consistency select').options].some(o=>o.value==='2020')")
        assert not js("[...document.querySelector('#reading-consistency select').options].some(o=>o.value==='2020')")
        js("const ankiYear=document.querySelector('#anki-consistency select');ankiYear.value='2020';ankiYear.dispatchEvent(new Event('change'))")
        assert '7 reviews' in js("document.querySelector('#anki-consistency [data-day=\"2020-11-12\"]').title")
        assert js("document.querySelector('#reading-consistency select').value")=='2026'
        # Graph and kanji buttons switch views directly and reuse cached data.
        original_insights=floating.load_insights
        insight_calls=[]
        def insight_group(name,characters):
            return dict(deck=name,cards=2,days={'2026-11-12':dict(reviews=3,seconds=60,retention_total=2,retention_pass=1,first=1)},answers=[1,0,2,0],hourly=[0]*12+[3]+[0]*11,stages=[1,0,1,0,0],intervals=[0,1,0,0,0,0],fields=['Expression'],kanji=[dict(char=char,seen=1,unseen=0,interval=30,strength=.4) for char in characters])
        insight_fixture=dict(catalog=floating.load_insights.__globals__['kanji_catalog'](),available_fields=['Expression','Definition'],combined=insight_group('Combined','日本語'),decks=[insight_group('Kaishi 1.5k','日本'),insight_group('Mining','語')],date='2026-11-16',interval=180)
        def fake_insights(config,**kwargs):
            insight_calls.append(config['decks']);return insight_fixture
        floating.load_insights=fake_insights
        assert not insight_calls and js("document.getElementById('anki-insights').hidden")
        assert js("document.getElementById('anki-graphs-toggle').nextElementSibling.id")=='anki-kanji-toggle'
        js("document.getElementById('anki-graphs-toggle').click()")
        wait_until(lambda:js("document.querySelectorAll('#anki-graphs .anki-graph').length===8"))
        assert len(insight_calls)==1
        assert js("document.querySelector('#anki-graphs').closest('.stats-surface').id")=='anki-consistency'
        assert not js("!!document.getElementById('anki-kanji-maps')")
        js("(()=>{const deck=document.getElementById('anki-graph-deck');deck.value='Mining';deck.dispatchEvent(new Event('change'));})()")
        assert js("document.getElementById('anki-graph-deck').value")=='Mining'
        js("document.getElementById('anki-kanji-toggle').click()")
        assert not js("!!document.getElementById('anki-graphs')")
        assert js("document.querySelectorAll('.anki-kanji-deck').length")==1
        assert js("document.querySelectorAll('.anki-kanji-deck[data-deck=Combined] [data-kanji-set=joyo] .anki-kanji-cell').length")==2136
        assert js("document.querySelectorAll('.anki-kanji-deck[data-deck=Combined] [data-status=missing]').length")==2133
        assert js("document.querySelector('#anki-kanji-maps').closest('.stats-surface').id")=='anki-consistency'
        js("window.savedKanjiGrid=document.querySelector('.anki-kanji-grid');updateReadingStats(readingStats)")
        assert js("window.savedKanjiGrid===document.querySelector('.anki-kanji-grid')")
        assert len(insight_calls)==1
        js("document.querySelector('#kanji-grid-options summary').click()")
        wait_until(lambda:window.stats_store.preference('kanji_grid_options',{}).get('options_open'))
        def grid_option(key,value):
            js("(()=>{const input=document.querySelector('[data-kanji-option="+key+"]');if(input.type==='checkbox')input.checked="+json.dumps(value)+";else input.value="+json.dumps(value)+";input.dispatchEvent(new Event('change'));})()")
            wait_until(lambda:window.stats_store.preference('kanji_grid_options',{}).get(key)==value)
        assert js("document.getElementById('kanji-grid-deck').value")=='combined'
        assert js("document.querySelector('[data-kanji-option=group]').options.length")==4
        def grid_deck(value):
            js("(()=>{const select=document.getElementById('kanji-grid-deck');select.value="+json.dumps(value)+";select.dispatchEvent(new Event('change'));})()")
            wait_until(lambda:window.stats_store.preference('kanji_grid_options',{}).get('deck')==value)
        for grouping in ('none','grade','jlpt'):
            grid_option('group',grouping)
            wait_until(lambda:js("document.querySelectorAll('.anki-kanji-deck').length")==1)
            assert js("document.querySelector('.anki-kanji-deck').dataset.deck")=='Combined'
            grid_deck('deck:Mining')
            wait_until(lambda:js("document.querySelector('.anki-kanji-deck').dataset.deck")=='Mining')
            assert js("document.querySelectorAll('.anki-kanji-deck').length")==1
            grid_deck('combined')
            wait_until(lambda:js("document.querySelector('.anki-kanji-deck').dataset.deck")=='Combined')
        assert not js("!!document.querySelector('[data-kanji-option=tooltips]')")
        assert js("document.querySelector('#kanji-grid-deck option[value=combined]').textContent")=='All decks'
        grid_option('group','decks')
        wait_until(lambda:js("document.querySelectorAll('.anki-kanji-deck').length")==1)
        assert js("document.querySelector('[data-kanji-option=group] option:checked').textContent")=='Selected deck'
        assert js("document.querySelectorAll('.anki-kanji-deck[data-deck=Combined] .anki-kanji-cell').length")==3
        grid_deck('deck:Mining')
        wait_until(lambda:js("document.querySelectorAll('.anki-kanji-deck').length")==1)
        assert js("document.querySelector('.anki-kanji-deck').dataset.deck")=='Mining'
        assert js("document.querySelectorAll('.anki-kanji-cell').length")==1
        grid_deck('combined');grid_option('group','none')
        wait_until(lambda:js("document.querySelector('.anki-kanji-deck').dataset.deck")=='Combined')
        assert len(insight_calls)==1
        grid_option('show_missing',False)
        wait_until(lambda:js("document.querySelectorAll('.anki-kanji-cell[data-status=missing]').length")==0)
        grid_option('show_missing',True)
        wait_until(lambda:js("document.querySelectorAll('.anki-kanji-cell[data-status=missing]').length")>0)
        grid_option('group','grade')
        wait_until(lambda:js("document.getElementById('anki-kanji-maps').textContent.includes('Grade 1 Kanji')"))
        grid_option('sort','unicode');grid_option('tile_size',40);grid_option('palette','kanjigrid')
        wait_until(lambda:js("getComputedStyle(document.querySelector('.anki-kanji-cell')).width")=='40px')
        js("document.getElementById('kanji-grid-fields').value='Expression';document.getElementById('kanji-grid-fields').dispatchEvent(new Event('change'))")
        wait_until(lambda:len(insight_calls)==2 and js("!!document.getElementById('anki-kanji-maps')"))
        assert window.stats_store.preference('kanji_grid_options',{})['fields']==['expression']
        js("document.getElementById('inline-settings').scrollTop=900")
        wait_until(lambda:not js("document.getElementById('stats-back-to-top').hidden"))
        js("document.getElementById('stats-back-to-top').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').scrollTop")<2)
        wait_until(lambda:js("document.getElementById('stats-back-to-top').hidden"))
        js("document.getElementById('inline-settings').scrollTop=document.getElementById('anki-consistency').offsetTop")
        window.web.grab().save('/tmp/ukijiten-joyo-grid-options.png')
        js("document.getElementById('anki-graphs-toggle').click()")
        assert js("document.querySelectorAll('#anki-graphs .anki-graph').length")==8
        assert not js("!!document.getElementById('anki-kanji-maps')")
        assert js("document.getElementById('anki-graph-deck').value")=='Mining'
        js("document.getElementById('anki-kanji-toggle').click()")
        assert js("!!document.getElementById('anki-kanji-maps')") and not js("!!document.getElementById('anki-graphs')")
        js("document.getElementById('anki-kanji-toggle').click()")
        assert js("document.getElementById('anki-insights').hidden")
        floating.load_insights=original_insights
        js("document.getElementById('stats-settings').click()")
        assert js("document.querySelector('.stats-top .settings-navigation').children.length")==2
        assert js("document.querySelector('.stats-top .settings-navigation button:nth-child(2)').classList.contains('dictionary-back-icon')")
        js("document.querySelector('.stats-top .settings-navigation button:nth-child(2)').click()")
        assert not js("!!document.getElementById('inline-settings')")
        window.open_reading_stats()
        wait_until(lambda:js("!!document.getElementById('stats-add')"))
        # The day cutoff is a saved stats setting and applies immediately.
        window.source_settings.values['gsm']['url']=f'ws://127.0.0.1:{feed_server.serverPort()}/ws/texthooker'
        js("document.getElementById('stats-settings').click()")
        assert js("!!document.getElementById('stats-day-boundary')")
        assert js("document.getElementById('stats-day-cutoff').value")=='0'
        js("document.getElementById('stats-day-cutoff').value='4';document.getElementById('stats-day-cutoff').dispatchEvent(new Event('input'));document.querySelector('.stats-source-settings').requestSubmit()")
        wait_until(lambda:window.stats_store.day_cutoff_hour()==4)
        wait_until(lambda:js("!document.querySelector('.stats-source-settings')"))
        assert json.loads((root/'stats-sources.json').read_text())['day']['cutoff_hour']==4
        js("document.getElementById('stats-settings').click()")
        assert js("document.getElementById('stats-day-cutoff').value")=='4'
        js("document.getElementById('stats-day-cutoff').value='0';document.getElementById('stats-day-cutoff').dispatchEvent(new Event('input'));document.querySelector('.stats-source-settings').requestSubmit()")
        wait_until(lambda:window.stats_store.day_cutoff_hour()==0)
        wait_until(lambda:js("!document.querySelector('.stats-source-settings')"))
        before_entry=window.stats_store.summary()
        js("document.getElementById('stats-add').click()")
        wait_until(lambda:js("!!document.getElementById('stats-entry-form')"))
        js("const entryForm=document.getElementById('stats-entry-form');entryForm.elements.characters.value='123';entryForm.elements.hours.value='1';entryForm.elements.minutes.value='15';entryForm.elements.description.value='Manual reading test';entryForm.elements.day.value='2020-11-13';updateReadingStats(readingStats)")
        assert js("document.getElementById('stats-entry-form').elements.description.value")=='Manual reading test'
        js("document.getElementById('stats-entry-form').requestSubmit()")
        wait_until(lambda:window.stats_store.summary()['total']==before_entry['total']+123)
        wait_until(lambda:js("!document.getElementById('stats-entry-form')"))
        assert window.stats_store.summary()['reading_seconds']==before_entry['reading_seconds']+4500
        assert window.stats_store.summary()['consistency_days']['2020-11-13']['characters']==123
        assert js("document.querySelector('#reading-consistency h3').textContent")=='Reading'
        assert js("!!(document.getElementById('reading-consistency').compareDocumentPosition(document.querySelector('.stats-sources')) & Node.DOCUMENT_POSITION_FOLLOWING)")
        js("document.getElementById('stats-settings').click()")
        assert js("document.getElementById('stats-manual-entries').textContent.includes('Manual reading test')")
        assert not js("!!document.querySelector('[data-source=manual]')")
        js("document.querySelector('.stats-top button').click()")
        js('closeSettings()');window.open_settings()
        avatar_before=window.settings['avatar']
        assert not js("document.getElementById('remove-avatar-folder').disabled")
        js("document.getElementById('remove-avatar-folder').click()")
        wait_until(lambda:window.settings['avatar_folder']=='')
        assert not window.avatar_timer.isActive()
        assert window.settings['avatar']==avatar_before
        assert Path(avatar_before).exists()
        assert js("document.getElementById('remove-avatar-folder').disabled")
        assert window.settings['avatar_hidden'] and window.avatar.isVisible()
        assert window.avatar.movie is None and window.avatar.pixmap().isNull()
        assert window.avatar.image_rect().isEmpty()
        js("document.getElementById('avatar-image-toggle').click()")
        wait_until(lambda:not window.settings['avatar_hidden'])
        assert not window.avatar.display_pixmap().isNull()

        js('closeSettings()')
        # Import a metadata-only frequency ZIP through the real Add dictionaries action.
        assert js("document.querySelector('.brand').textContent").strip()=='浮き辞典'
        window.open_native_manager()
        app.processEvents()
        frequency_zip=root/'frequency.zip'
        with zipfile.ZipFile(frequency_zip,'w') as archive:
            archive.writestr('index.json',json.dumps({'title':'Test frequency','format':3}))
            archive.writestr('term_meta_bank_1.json',json.dumps([['先生','freq',{'reading':'せんせい','frequency':42}]]))
        original_picker=manager_module.QFileDialog.getOpenFileNames
        manager_module.QFileDialog.getOpenFileNames=lambda *args:([str(frequency_zip)],'')
        try:window.manager.add_dictionary_button.click()
        finally:manager_module.QFileDialog.getOpenFileNames=original_picker
        wait_until(lambda:window.manager.import_thread is None)
        assert '1 imported' in window.manager.dictionary_status.text(),window.manager.dictionary_status.text()
        assert window.manager.dictionary_list.count()==4
        assert window.manager.dictionary_list.horizontalScrollBar().maximum()==0
        window.dictionary_overlay.grab().save('/tmp/ukijiten-dictionaries.png')
        window.close_dictionary_manager()
        # Disabled NHK provides metadata in both views without becoming a definition result.
        pitch_definition=json.dumps([{'type':'structured-content','content':{'tag':'span','data':{'pitchAccentText':'true','accentSig':'センセ＼ー'}}}])
        with window.db:
            window.db.execute("INSERT INTO dictionaries(id,title,path,enabled,sort_order,has_pitch) VALUES(99,'NHK-pitch','nhk.zip',0,99,1)")
            window.db.execute('INSERT INTO entries VALUES(?,?,?,?)',(99,'先生','せんせい',pitch_definition))
        window.open_manager()
        wait_until(lambda:js("!!document.getElementById('dictionary-popup-settings')"))
        assert not js("!!document.getElementById('popup-settings')")
        js("document.getElementById('dictionary-popup-settings').click()")
        wait_until(lambda:js("document.querySelectorAll('.metadata-selector').length===2"))
        assert js("document.querySelectorAll('#popup-dictionary-list > div').length")==3
        assert not js("document.getElementById('popup-dictionary-list').textContent.includes('NHK-pitch')")
        js("document.querySelector('[data-metadata-key=frequency_paths]').click();document.querySelector('[data-metadata-key=pitch_paths]').click()")
        wait_until(lambda:window.popup_config.values['frequency_paths']==[str(frequency_zip)] and window.popup_config.values['pitch_paths']==['nhk.zip'])
        pump_for(.25)
        assert js("!!document.getElementById('inline-settings')")
        window.web.grab().save('/tmp/ukijiten-metadata-settings.png')
        js('closeSettings()')
        # Main metadata controls are independent from the popup's controls.
        assert window.metadata_selection()==((),())
        window.open_manager()
        wait_until(lambda:js("!!document.querySelector('#inline-settings[data-page=dictionaries]')"))
        assert js("document.querySelectorAll('#main-dictionary-list > div').length")==3
        assert js("document.getElementById('dictionary-add').previousElementSibling.id")=='dictionary-popup-settings'

        js("document.querySelector('[data-metadata-key=main_frequency_paths]').click();document.querySelector('[data-metadata-key=main_pitch_paths]').click()")
        wait_until(lambda:window.metadata_selection()==window.popup_metadata_selection())
        QTest.qWait(200)
        assert js("!!document.querySelector('#inline-settings[data-page=dictionaries]')")
        window.web.grab().save('/tmp/ukijiten-new-dictionary-settings.png')
        # Row switches persist immediately and leave popup definition choices alone.
        original_ids=[row[0] for row in window.db.execute('SELECT id FROM dictionaries ORDER BY sort_order,id')]
        js("document.querySelector('#main-dictionary-list > div .popup-order-buttons button:nth-child(2)').click()")
        wait_until(lambda:[row[0] for row in window.db.execute('SELECT id FROM dictionaries ORDER BY sort_order,id')]!=original_ids)
        reordered=[row[0] for row in window.db.execute('SELECT id FROM dictionaries ORDER BY sort_order,id')]
        assert reordered[3:]==original_ids[3:]
        js("document.querySelector('#main-dictionary-list > div:nth-child(2) .popup-order-buttons button').click()")
        wait_until(lambda:[row[0] for row in window.db.execute('SELECT id FROM dictionaries ORDER BY sort_order,id')]==original_ids)
        popup_disabled=list(window.popup_config.values['disabled_paths'])
        before=window.db.execute('SELECT enabled FROM dictionaries WHERE id=1').fetchone()[0]
        js("document.querySelector('#main-dictionary-list [data-id=\"1\"] input').click()")
        wait_until(lambda:window.db.execute('SELECT enabled FROM dictionaries WHERE id=1').fetchone()[0]!=before)
        assert window.popup_config.values['disabled_paths']==popup_disabled
        js("document.querySelector('#main-dictionary-list [data-id=\"1\"] input').click()")
        wait_until(lambda:window.db.execute('SELECT enabled FROM dictionaries WHERE id=1').fetchone()[0]==before)
        js('closeSettings()')
        ui_queries=[]
        window.db.set_trace_callback(ui_queries.append)
        js("setQuery('先生')");window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        wait_until(lambda:js("!!document.querySelector('.entry .pitch-graph')"))
        window.db.set_trace_callback(None)
        assert not any('term_metadata' in sql or 'FROM entries' in sql for sql in ui_queries),ui_queries
        assert js("document.querySelector('.entry .frequency-value').textContent")=='42'
        js("document.getElementById('lookup-split').click();secondaryQuery.value='先生';secondaryQuery.dispatchEvent(new Event('input',{bubbles:true}))")
        wait_until(lambda:js("!!secondaryResults.querySelector('.pitch-graph') && secondaryResults.querySelector('.frequency-value')?.textContent==='42'"))
        js("resetLookupGrid()")

        assert not js("!!document.getElementById('dict-99')")
        # A heading folds its full dictionary; defaults persist and apply to both lookups.
        collapse_path=js("results.querySelector('details.dictionary').dataset.dictionaryPath")
        js("results.querySelector('details.dictionary > summary').click()")
        assert not js("results.querySelector('details.dictionary').open")
        assert js("[...results.querySelectorAll('details.dictionary')].slice(1).every(group=>group.open)")
        window.web.setFocus()
        js("results.querySelector('details.dictionary > summary').focus()")
        assert js("document.activeElement.tagName")=='SUMMARY'
        QTest.keyClick(window.web.focusProxy(),Qt.Key.Key_Return)
        wait_until(lambda:js("results.querySelector('details.dictionary').open"))
        assert js("results.querySelector('details.dictionary').open")
        js("results.querySelector('.dictionary-collapse-defaults').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').dataset.page==='collapse-defaults'"))
        assert js("document.querySelector('.settings-navigation').children[0].textContent")=='← Dictionaries'
        assert js("document.querySelector('.settings-navigation').children[1].classList.contains('dictionary-back-icon')")
        js("document.querySelector('.settings-navigation button').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').dataset.page==='dictionaries'"))
        js("document.getElementById('dictionary-collapse-settings').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').dataset.page==='collapse-defaults'"))
        # Collapse defaults are independent of whether a dictionary is in use.
        assert js("document.querySelector('[data-collapse-group=in-use] h3').textContent")=='In use'
        expected_in_use=[row['path'] for row in json.loads(window.dictionary_payload()) if row['enabled'] and not row['frequency'] and not row['pitch']]
        actual_in_use=js("JSON.stringify([...document.querySelectorAll('[data-collapse-group=in-use] [data-collapse-path]')].map(row=>row.dataset.collapsePath))")
        assert json.loads(actual_in_use)==expected_in_use,(actual_in_use,expected_in_use)
        inactive_row="document.querySelector('[data-collapse-path=\"dict-3.zip\"]')"
        assert js(inactive_row+".closest('[data-collapse-group]').dataset.collapseGroup")=='other'
        js(inactive_row+".querySelector('input').click()")
        wait_until(lambda:'dict-3.zip' in window.popup_config.values['main_collapsed_paths'])
        assert window.db.execute('SELECT enabled FROM dictionaries WHERE id=3').fetchone()[0]==0
        js("document.querySelector('.settings-navigation button').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').dataset.page==='dictionaries'"))
        js("document.querySelector('#main-dictionary-list [data-id=\"3\"] input').click()")
        wait_until(lambda:window.db.execute('SELECT enabled FROM dictionaries WHERE id=3').fetchone()[0]==1)
        js("document.getElementById('dictionary-collapse-settings').click()")
        wait_until(lambda:js("document.getElementById('inline-settings').dataset.page==='collapse-defaults'"))
        assert js(inactive_row+".closest('[data-collapse-group]').dataset.collapseGroup")=='in-use'
        assert js(inactive_row+".querySelector('input').checked")
        assert js("document.querySelectorAll('[data-collapse-path=\"dict-3.zip\"]').length")==1
        # A catalog update also regroups an already open page without toggling it.
        window.dictionary_action('toggle',{'id':3,'enabled':False})
        wait_until(lambda:js(inactive_row+".closest('[data-collapse-group]').dataset.collapseGroup")== 'other')
        assert js(inactive_row+".querySelector('input').checked")
        js(inactive_row+".querySelector('input').click()")
        wait_until(lambda:'dict-3.zip' not in window.popup_config.values['main_collapsed_paths'])
        js("[...document.querySelectorAll('[data-collapse-path]')].find(row=>row.dataset.collapsePath==="+json.dumps(collapse_path)+").querySelector('input').click()")
        wait_until(lambda:collapse_path in window.popup_config.values['main_collapsed_paths'])
        window.web.grab().save('/tmp/ukijiten-collapse-defaults.png')
        from popup_settings import PopupSettings
        assert collapse_path in PopupSettings(window.popup_config.path,[]).values['main_collapsed_paths']
        wait_until(lambda:not js("results.querySelector('details.dictionary').open"))
        assert not js("secondaryResults.querySelector('details.dictionary').open")
        js('closeSettings()');window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        wait_until(lambda:not js("results.querySelector('details.dictionary').open"))
        js("results.querySelector('.dictionary-nav a').click()")
        assert js("results.querySelector('details.dictionary').open")
        assert not js("secondaryResults.querySelector('details.dictionary').open")
        js("results.querySelector('.dictionary-collapse-defaults').click()")
        wait_until(lambda:js("!!document.querySelector('[data-collapse-path] input')"))
        assert js("[...document.querySelectorAll('[data-collapse-path]')].find(row=>row.dataset.collapsePath==="+json.dumps(collapse_path)+").querySelector('input').checked")
        js("[...document.querySelectorAll('[data-collapse-path]')].find(row=>row.dataset.collapsePath==="+json.dumps(collapse_path)+").querySelector('input').click()")
        wait_until(lambda:not window.popup_config.values['main_collapsed_paths'])
        js('closeSettings()')
        assert window.db.execute('SELECT enabled FROM dictionaries WHERE id=99').fetchone()[0]==0
        window.hover_worker.submit(json.dumps([{'text':'先生','length':2}]))
        wait_until(lambda:window.hover_worker.pending is None)
        assert 'pitch-graph' in window.popup_markup and '[3]' in window.popup_markup
        assert 'Test frequency' in window.popup_markup and '>42<' in window.popup_markup
        window.web.grab().save('/tmp/ukijiten-search-metadata.png')
        # Popup switches affect only the nested view, including its pitch accents.
        main_selection=window.metadata_selection()
        window.open_popup_settings()
        js("document.querySelector('[data-metadata-key=frequency_paths]').click();document.querySelector('[data-metadata-key=pitch_paths]').click()")
        wait_until(lambda:window.popup_metadata_selection()==((),()))
        assert window.metadata_selection()==main_selection
        js('closeSettings()');pump_for(.15)
        previous_popup_generation=window.popup_generation
        window.hover_worker.submit(json.dumps([{'text':'先生','length':2}]))
        wait_until(lambda:window.popup_generation>previous_popup_generation)
        assert 'pitch-graph' not in window.popup_markup and 'frequency-value' not in window.popup_markup
        window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        wait_until(lambda:js("!!document.querySelector('.entry .pitch-graph') && !!document.querySelector('.entry .frequency-value')"))
        pump_for(.15)
        window.hover_popup.grab().save('/tmp/nhk-pitch-popup.png')
        with window.db:
            window.db.execute("INSERT INTO dictionaries(id,title,path,enabled,sort_order,has_frequency,has_pitch) VALUES(100,'Extra source','extra.zip',0,100,1,1)")
            window.db.execute('INSERT INTO term_metadata VALUES(?,?,?,?)',(100,'先生','freq','84'))
            window.db.execute('INSERT INTO term_metadata VALUES(?,?,?,?)',(100,'先生','pitch',json.dumps({'reading':'せんせい','pitches':[{'position':0}]})))
        window.open_manager()
        wait_until(lambda:js("!!document.getElementById('dictionary-popup-settings')"))
        assert not js("document.getElementById('inline-settings').textContent.includes('Entry metadata')")
        js("document.querySelector('.metadata-selector[data-kind=frequency]').open=true")
        assert js("document.querySelector('.metadata-selector[data-kind=frequency] .popup-order-buttons button').getBoundingClientRect().width")<=30

        assert js("!!document.querySelector('.dictionary-back-icon svg')")
        js("document.querySelector('[data-metadata-key=main_frequency_paths][data-path=\"extra.zip\"]').click();document.querySelector('[data-metadata-key=main_pitch_paths][data-path=\"extra.zip\"]').click();for(const kind of ['frequency','pitch'])document.querySelector('.metadata-selector[data-kind='+kind+'] .metadata-source-row[data-path=\"extra.zip\"] button').click()")
        wait_until(lambda:window.metadata_selection()[0][0]=='extra.zip' and window.metadata_selection()[1][0]=='extra.zip')
        js('closeSettings()');window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        wait_until(lambda:js("document.querySelectorAll('.entry .pitch-row .pitch-source').length>=2"))
        assert js("document.querySelector('.entry .frequency-value').textContent")=='84'
        assert js("(()=>{const rows=document.querySelector('.entry .pitch-row').children;return rows.length===2&&Math.abs(rows[0].getBoundingClientRect().y-rows[1].getBoundingClientRect().y)<2;})()")
        assert js("""(()=>{
          for(const selector of ['.frequency-row','.pitch-row']){
            const row=document.querySelector('.entry '+selector),saved=row.style.cssText;
            row.style.width='180px';
            const children=[...row.children],style=getComputedStyle(row);
            const wraps=children.some(child=>child.getBoundingClientRect().top>children[0].getBoundingClientRect().top+5);
            const fits=row.scrollWidth<=row.clientWidth+1;
            row.style.cssText=saved;
            if(style.flexWrap!=='wrap'||!wraps||!fits)return false;
          }
          return true;
        })()""")
        js('motion.auto_fade=false;setWindowActive(true);showPanel()')
        QTest.qWait(600);window.web.repaint();window.web.grab().save('/tmp/ukijiten-ordered-pitch-row.png')
        window.open_popup_settings()
        wait_until(lambda:js("!!document.querySelector('.settings-navigation')"))
        assert js("document.querySelector('.settings-navigation').children[1].classList.contains('dictionary-back-icon')")
        assert js("document.querySelector('#inline-settings .settings-section > summary').textContent")=='Scanning'
        js("for(const input of document.querySelectorAll('[data-metadata-key]'))if(!input.checked)input.click();for(const kind of ['frequency','pitch'])document.querySelector('.metadata-selector[data-kind='+kind+'] .metadata-source-row[data-path=\"extra.zip\"] button').click()")
        wait_until(lambda:window.popup_metadata_selection()[0][0]=='extra.zip' and window.popup_metadata_selection()[1][0]=='extra.zip')
        js('closeSettings()');window.hover_worker.submit(json.dumps([{'text':'先生','length':2}]))
        wait_until(lambda:window.hover_worker.pending is None)
        assert window.popup_markup.index('Extra source pitch accent')<window.popup_markup.index('NHK-pitch pitch accent')
        # Main settings expose independent entry sizes, persisted and applied to both views.
        window.open_settings()
        wait_until(lambda:js("!!document.querySelector('[data-setting=font_headword] input')"))
        assert js("[...document.querySelectorAll('#toolbar button')].every(button=>getComputedStyle(button).visibility==='hidden')")
        assert js("!!(document.querySelector('.settings-source-buttons').compareDocumentPosition(document.querySelector('[data-setting=font_headword]'))&Node.DOCUMENT_POSITION_FOLLOWING)")
        assert js("!!(document.querySelector('[data-setting=font_frequency]').compareDocumentPosition(document.querySelector('[data-setting=font_pitch]'))&Node.DOCUMENT_POSITION_FOLLOWING)")
        assert not js("document.getElementById('inline-settings').textContent.includes('Manage dictionaries')")
        js("document.querySelector('[data-section=main-entry-text-size]').open=true")
        assert js("document.querySelector('[data-section=main-entry-text-size]').parentElement.querySelector('[data-setting]').dataset.setting")=='font_family'
        assert js("document.querySelector('[data-setting=font_headword] span').textContent")=='Headword (px)'
        assert js("[...document.querySelectorAll('[data-setting=font_family] optgroup')].some(group=>group.label==='Chinese · Simplified')")
        js("const entryFont=document.querySelector('[data-setting=font_family] select');entryFont.value='Yomogi';entryFont.dispatchEvent(new Event('change',{bubbles:true}))")
        wait_until(lambda:window.settings['font_family']=='Yomogi')
        assert floating.load_settings()['font_family']=='Yomogi'
        js("document.fonts.load('16px Yomogi','日本語').then(()=>window.entryFontLoaded=true)")
        wait_until(lambda:js('!!window.entryFontLoaded'))
        assert js("document.fonts.check('16px Yomogi','日本語')")
        QTest.qWait(150);window.web.grab().save('/tmp/ukijiten-compact-settings.png')


        for key,value in [('font_headword',34),('font_definition',19),('font_example',17),('font_frequency',16),('font_pitch',18)]:
            js("(()=>{const input=document.querySelector('[data-setting="+key+"] input');input.value="+str(value)+";input.dispatchEvent(new Event('input',{bubbles:true}));})()")
            wait_until(lambda key=key,value=value:window.settings[key]==value)
        js('closeSettings()');window.search('先生')
        wait_until(lambda:window.lookup_worker.pending is None)
        assert js("getComputedStyle(document.querySelector('.entry h3')).fontSize")=='34px'
        assert js("getComputedStyle(document.querySelector('.entry .definition')).fontSize")=='19px'
        assert js("getComputedStyle(document.querySelector('.entry .frequency-row')).fontSize")=='16px'
        assert js("getComputedStyle(document.querySelector('.entry .pitch-row')).fontSize")=='18px'
        assert js("getComputedStyle(document.querySelector('.entry h3')).fontFamily").startswith('Yomogi')
        assert not js("getComputedStyle(document.querySelector('#toolbar')).fontFamily").startswith('Yomogi')
        window.open_popup_settings()
        wait_until(lambda:js("!!document.getElementById('popup-background_color')"))
        js("const popupColor=document.getElementById('popup-background_color');popupColor.value='#d9efd8';popupColor.dispatchEvent(new Event('change'))")
        wait_until(lambda:window.popup_config.values['background_color']=='#d9efd8')
        js("document.getElementById('popup-background_color').click()")
        wait_until(lambda:window.color_dialog is not None)
        window.color_dialog.setCurrentColor(QColor('#314159'))
        wait_until(lambda:window.popup_config.values['background_color']=='#314159')
        window.color_dialog.reject()
        wait_until(lambda:window.color_dialog is None and window.popup_config.values['background_color']=='#d9efd8')
        js('closeSettings()');window.hover_worker.submit(json.dumps([{'text':'先生','length':2}]))
        wait_until(lambda:window.hover_worker.pending is None)
        popup_appearance=[]
        window.hover_popup.page().runJavaScript("JSON.stringify([getComputedStyle(document.body).backgroundColor,getComputedStyle(document.querySelector('article h2')).fontSize,getComputedStyle(document.querySelector('article h2')).fontFamily])",popup_appearance.append)
        wait_until(lambda:bool(popup_appearance))
        appearance=json.loads(popup_appearance[0])
        assert appearance[:2]==['rgb(217, 239, 216)','34px'] and appearance[2].startswith('Yomogi'),popup_appearance
        window.update_preference('font_family','Noto Sans CJK SC')
        assert floating.load_settings()['font_family']=='Noto Sans CJK SC'
        window.update_preference('font_family','')
        wait_until(lambda:js("!document.documentElement.style.getPropertyValue('--entry-font-family')"))
        # Popup stays open across leave/scroll/blur and can move without snapping back.
        js("document.getElementById('lookup-area').dispatchEvent(new PointerEvent('pointerleave'));window.dispatchEvent(new Event('blur'))")
        QApplication.sendEvent(window.hover_popup,QEvent(QEvent.Type.Leave));window.bridge.hide_hover()
        window.popup_application_state(Qt.ApplicationState.ApplicationInactive)
        QTest.qWait(800)
        assert window.hover_popup.isVisible()
        position=window.hover_popup.pos()
        window.bridge.popup_drag_start(100,100);window.popup_system_move=False
        window.bridge.popup_drag_move(140,130);window.bridge.popup_drag_end()
        assert window.hover_popup.pos()==position+QPoint(40,30)
        window.update_popup_content()
        assert window.hover_popup.pos()==position+QPoint(40,30)
        window.open_popup_settings()
        wait_until(lambda:js("!!document.getElementById('popup-opacity')"))
        js("document.getElementById('popup-opacity').value=45;document.getElementById('popup-opacity').dispatchEvent(new Event('input'))")
        wait_until(lambda:window.popup_config.values['opacity']==45)
        opacity=[];window.hover_popup.page().runJavaScript('getComputedStyle(document.body).backgroundColor',opacity.append)
        wait_until(lambda:bool(opacity))
        assert opacity[0]=='rgba(217, 239, 216, 0.45)',opacity
        from time import monotonic
        window.last_popup_press=monotonic();window.global_popup_click(window.last_popup_press)
        QTest.qWait(250);assert window.hover_popup.isVisible()
        QTest.qWait(80);window.global_popup_click(monotonic())
        QTest.qWait(250);assert not window.hover_popup.isVisible()
        js('closeSettings()')
        # Preserve the user's chosen avatar share across orientation, images, saves and window sizes.
        window.resize(1000,800);QTest.qWait(100)
        avatar_index=window.splitter.indexOf(window.avatar)
        window.splitter.setSizes([400,600] if avatar_index==0 else [600,400]);window.splitter_moved()
        ratio=window.settings['splitter_ratio']
        for _ in range(4):
            window.rotate_panes();QTest.qWait(80)
            assert abs(window.settings['splitter_ratio']-ratio)<.001
            sizes=window.splitter.sizes()
            assert abs(sizes[window.splitter.indexOf(window.avatar)]/sum(sizes)-ratio)<.015
        window.flip_horizontal();QTest.qWait(100)
        window.avatar.set_image(str(second));QTest.qWait(100);window.save_preferences()
        assert abs(window.settings['splitter_ratio']-ratio)<.001
        assert abs(floating.load_settings()['splitter_ratio']-ratio)<.001
        window.open_settings()
        wait_until(lambda:js("!!document.getElementById('avatar-toggle')"))
        assert js("document.getElementById('remove-avatar-folder').parentElement.classList.contains('folder-picker-control')")
        assert not js("!!document.querySelector('#toolbar #avatar-toggle')")
        assert js("document.getElementById('avatar-toggle').textContent")=='Dict. Only'
        old_sizes=window.splitter.sizes()
        js("document.getElementById('avatar-image-toggle').click()")
        wait_until(lambda:window.settings['avatar_hidden'])
        QTest.qWait(80)
        assert window.avatar.isVisible() and window.avatar.pixmap().isNull()
        assert window.splitter.sizes()==old_sizes
        js("document.getElementById('avatar-image-toggle').click()")
        wait_until(lambda:not window.settings['avatar_hidden'])
        assert not window.avatar.display_pixmap().isNull()

        js("document.getElementById('avatar-toggle').click()")
        wait_until(lambda:not window.settings['avatar_enabled'] and not window.avatar.isVisible())
        QTest.qWait(150)
        assert window.web.width()>=window.splitter.width()-2
        window.settings['auto_fade']=True;window.panel_visible=False
        window.apply_panel_input_mask()
        mask=window.windowHandle().mask()
        assert mask.contains(QPoint(window.width()-1,window.height()//2))
        assert not mask.contains(QPoint(window.width()//2,window.height()//2))
        window.focus_timer.stop()
        js("motion.auto_fade=true;panelHovered=false;imageHovered=false;windowActive=false;setPanelVisible(false)")
        wait_until(lambda:not window.panel_visible)
        center=QPoint(window.width()//2,window.height()//2)
        QApplication.sendEvent(window,QEnterEvent(QPointF(center),QPointF(center),QPointF(window.mapToGlobal(center))))
        QTest.qWait(80)
        assert not window.panel_visible
        edge=QPoint(window.width()-1,window.height()//2)
        QApplication.sendEvent(window,QEnterEvent(QPointF(edge),QPointF(edge),QPointF(window.mapToGlobal(edge))))
        wait_until(lambda:window.panel_visible)
        assert window.windowHandle().mask().isEmpty()
        window.focus_timer.start()

        window.settings['auto_fade']=False;window.apply_panel_input_mask()
        assert window.windowHandle().mask().isEmpty()
        window.panel_visible=True;window.settings['auto_fade']=False
        js('motion.auto_fade=false;showPanel()')

        assert abs(window.settings['splitter_ratio']-ratio)<.001
        js("document.getElementById('avatar-toggle').click()")
        wait_until(lambda:window.settings['avatar_enabled'] and window.avatar.isVisible())
        QTest.qWait(150)
        sizes=window.splitter.sizes()
        assert abs(sizes[window.splitter.indexOf(window.avatar)]/sum(sizes)-ratio)<.015

        # The shared native editor exports copies, keeps the splitter share,
        # and gives avatar/background independent automatic mirror settings.
        edit_source=root/'editable.png';editable=QImage(80,160,QImage.Format.Format_RGBA8888);editable.fill(QColor(70,140,220,110));editable.save(str(edit_source));original_bytes=edit_source.read_bytes()
        def apply_image_dialog(dialog):
            dialog.transform_image('horizontal');dialog.output_width.setValue(160)
            dialog.fill.setChecked(True);dialog.auto_sides.setChecked(True);dialog.auto_vertical.setChecked(True)
            return floating.QDialog.DialogCode.Accepted
        saved_ratio=window.settings['splitter_ratio']
        with patch.object(floating.ImageEditDialog,'exec',apply_image_dialog):
            window.edit_image(str(edit_source),'avatar');window.edit_image(str(edit_source),'background')
        assert edit_source.read_bytes()==original_bytes
        assert window.settings['avatar_fill_pane'] and window.settings['background_auto_mirror_sides']
        assert abs(window.settings['splitter_ratio']-saved_ratio)<.001
        assert QImage(window.settings['avatar']).pixelColor(0,0).alpha()==110
        window.flip_horizontal();QTest.qWait(60)
        assert window.settings['avatar_mirror_x'] and window.settings['background_mirror_x']
        assert js("getComputedStyle(document.documentElement).getPropertyValue('--background-scale-x').trim()")=='-1'
        window.toggle_avatar_vertical_position();QTest.qWait(60)
        assert not window.settings['avatar_mirror_x'] and not window.settings['background_mirror_x']
        assert abs(window.settings['splitter_ratio']-saved_ratio)<.001
        window.settings['background_auto_mirror_sides']=False
        window.flip_horizontal();QTest.qWait(60)
        assert window.settings['avatar_mirror_x'] and not window.settings['background_mirror_x']

        # Editing the displayed folder image must preserve the cycle and remember
        # the original -> edited association across removal, restart and selection.
        avatar_folder=root/'avatar-cycle';avatar_folder.mkdir()
        for name,color in [('a.png','red'),('b.png','blue')]:
            image=QImage(80,160,QImage.Format.Format_RGBA8888);image.fill(QColor(color));image.save(str(avatar_folder/name))
        window.update_preference('avatar_folder',str(avatar_folder))
        source=str(avatar_folder/'a.png');assert window.settings['avatar']==source
        cycle_index=window.avatar_index
        def crop_cycle_image(dialog):
            from PySide6.QtCore import QRectF
            assert not window.avatar_timer.isActive()
            dialog.canvas.crop=QRectF(10,20,40,80);dialog.crop_check.setChecked(True);dialog.crop_changed()
            return floating.QDialog.DialogCode.Accepted
        with patch.object(floating.ImageEditDialog,'exec',crop_cycle_image):window.bridge.edit_current_image('avatar')
        edited=window.settings['avatar']
        assert edited!=source and (QImage(edited).width(),QImage(edited).height())==(40,80)
        assert window.settings['avatar_folder']==str(avatar_folder) and window.avatar_timer.isActive()
        assert window.avatar_index==cycle_index
        window.next_avatar();assert window.settings['avatar']==str(avatar_folder/'b.png')
        window.configure_avatar_rotation()
        assert window.settings['avatar']==str(avatar_folder/'b.png')
        window.next_avatar();assert window.settings['avatar']==edited
        window.update_preference('avatar_folder','')
        window.image_edits=floating.ImageEditLibrary(root)
        window.update_preference('avatar_folder',str(avatar_folder))
        assert window.settings['avatar']==edited and window.avatar_timer.isActive()
        def cancel_saved_crop(dialog):
            assert dialog.specification()['crop']==[10,20,40,80]
            assert not window.avatar_timer.isActive()
            return floating.QDialog.DialogCode.Rejected
        with patch.object(floating.ImageEditDialog,'exec',cancel_saved_crop):window.bridge.edit_current_image('avatar')
        assert window.avatar_timer.isActive() and window.settings['avatar']==edited
        window.update_preference('avatar_folder','')
        with patch.object(floating.ImageEditDialog,'exec',cancel_saved_crop):window.edit_image(source,'avatar')
        assert window.settings['avatar_hidden']
        def accept_saved_crop(dialog):
            cancel_saved_crop(dialog)
            return floating.QDialog.DialogCode.Accepted
        with patch.object(floating.QFileDialog,'getOpenFileName',return_value=(source,'')),patch.object(floating.ImageEditDialog,'exec',accept_saved_crop):window.bridge.choose_image()
        assert window.settings['avatar']==edited and not window.avatar_timer.isActive()

        # Translation uses the same pane and keeps local detection/network work
        # off the UI thread. Stub model generation to avoid external charges.
        original_translate=floating.translate;original_models=floating.load_models
        translation_calls=[]
        floating.translate=lambda settings,text,target,cancelled:translation_calls.append((text,target)) or {'translation':'This is a translation test.','source_language':'Japanese'}
        floating.load_models=lambda provider,profile:['test-model']
        window.resize(1600,820);app.processEvents()
        assert js("document.getElementById('reading-stats-button').nextElementSibling.id")=='translation-button'
        js("document.getElementById('translation-button').click()")
        wait_until(lambda:js("!!document.querySelector('.translation-pane')"))
        assert not js("document.querySelector('.translation-connection').open")
        assert js("document.querySelectorAll('.translation-editor textarea').length")==2
        assert js("document.getElementById('translation-run').textContent")=='Translate (Ctrl+Enter)'
        assert js("parseFloat(getComputedStyle(document.querySelector('.translation-shortcut')).fontSize)<parseFloat(getComputedStyle(document.getElementById('translation-run')).fontSize)*.75")
        js("const translationInput=document.getElementById('translation-input');translationInput.value='これは翻訳のテストです。';translationInput.dispatchEvent(new Event('input'));document.getElementById('translation-load-models').click()")
        wait_until(lambda:js("document.getElementById('translation-source-language').textContent==='Japanese'"))
        wait_until(lambda:js("document.getElementById('translation-model').value==='test-model'"))
        js("document.getElementById('translation-model').value='edited-model';document.getElementById('translation-model').dispatchEvent(new Event('input'));document.getElementById('translation-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true}))")
        wait_until(lambda:js("document.getElementById('translation-output').value==='This is a translation test.'"))
        assert len(translation_calls)==1
        js("document.getElementById('translation-output').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true}))")
        wait_until(lambda:len(translation_calls)==2 and not js('translationState.busy'))
        assert window.translator.settings.profile()[1]['model']=='edited-model'
        assert js("(()=>{const boxes=[...document.querySelectorAll('.translation-editor')].map(e=>e.getBoundingClientRect());return Math.abs(boxes[0].top-boxes[1].top)<1&&boxes[1].left>boxes[0].right;})()")
        js("document.getElementById('translation-copy').click()")
        wait_until(lambda:QApplication.clipboard().text()=='This is a translation test.')
        window.web.grab().save('/tmp/ukijiten-translation-wide.png')
        window.resize(510,820);QTest.qWait(120)
        assert js("(()=>{const boxes=[...document.querySelectorAll('.translation-editor')].map(e=>e.getBoundingClientRect());return Math.abs(boxes[0].top-boxes[1].top)<1;})()")
        js("document.getElementById('translation-layout').click()")
        wait_until(lambda:window.translator.settings.values['layout']=='rows')
        assert js("(()=>{const boxes=[...document.querySelectorAll('.translation-editor')].map(e=>e.getBoundingClientRect());return boxes[1].top>boxes[0].bottom&&Math.abs(boxes[0].left-boxes[1].left)<1;})()")
        window.web.grab().save('/tmp/ukijiten-translation-narrow.png')
        js("closeSettings();document.getElementById('translation-button').click()")
        wait_until(lambda:js("document.getElementById('translation-input')?.value==='これは翻訳のテストです。'"))
        assert js("document.querySelector('.translation-editors').dataset.layout")=='rows'
        assert js("document.getElementById('translation-output').value")=='This is a translation test.'
        js('closeSettings()');window.resize(990,670)
        floating.translate=original_translate;floating.load_models=original_models

        # Native character banks support main and nested headword clicks without
        # replacing the underlying word search, including supplementary hanzi.
        character_zip=root/'characters.zip'
        with zipfile.ZipFile(character_zip,'w') as archive:
            archive.writestr('index.json',json.dumps({'title':'Character fixture','format':3}))
            archive.writestr('kanji_bank_1.json',json.dumps([
                ['先','セン','さき','',['precede'],{'strokes':'6'}],
                ['𠮟','chì','','',['Supplementary hanzi'],{}]],ensure_ascii=False))
            archive.writestr('kanji_meta_bank_1.json',json.dumps([['先','freq',25]]))
        manager_module.Importer([character_zip]).run()
        with window.db:window.db.execute('UPDATE dictionaries SET enabled=1')
        js("closeSettings();query.value='先生';app.search(query.value)")
        wait_until(lambda:js("!!results.querySelector('h3 [data-character=先]')"))
        js("results.querySelector('h3 [data-character=先]').click()")
        wait_until(lambda:js("!!results.querySelector('.character-page')"))
        assert window.query=='先生' and js("results.textContent.includes('precede') && results.textContent.includes('25')")
        assert not window.hover_popup or not window.hover_popup.isVisible()
        js("results.querySelector('.lookup-detail-back').click()")
        assert js("!!results.querySelector('h3 [data-character=先]')") and window.query=='先生'
        assert not js("!!results.querySelector('a[data-source-id]')")
        window.show_hover_results('',[('先生','せんせい','["Teacher"]',1,'Word fixture')],'')
        wait_until(lambda:window.popup_ready and window.hover_popup.isVisible())
        def popup_js(code):
            value=[];window.hover_popup.page().runJavaScript(code,value.append)
            wait_until(lambda:bool(value));return value[0]
        wait_until(lambda:popup_js("!!document.querySelector('h2 [data-character=先]')"))
        popup_js("document.querySelector('h2 [data-character=先]').click()")
        wait_until(lambda:js("!!results.querySelector('.character-page')"))
        assert not window.hover_popup.isVisible()
        js("results.querySelector('.lookup-detail-back').click()")
        window.bridge.kanji_lookup('𠮟',100,100,False)
        wait_until(lambda:js("results.textContent.includes('Supplementary hanzi')"))
        js("results.querySelector('.lookup-detail-back').click()")
        assert js("!!results.querySelector('h3 [data-character=先]')")

        window.open_manager()
        wait_until(lambda:js("document.querySelectorAll('[data-character-source]').length") == 2)
        assert js("!!document.getElementById('dictionary-import-status').previousElementSibling.querySelector('#dictionary-add')")
        assert not js("!!document.querySelector('#main-dictionary-list [data-id=\"'+"+str(window.db.execute('SELECT id FROM dictionaries WHERE path=?',(str(character_zip),)).fetchone()[0])+"+'\"]')")
        js("closeSettings();document.getElementById('lookup-split').click();document.getElementById('lookup-add-row').click()")
        wait_until(lambda:js("!!document.querySelector('.lookup-grid-divider[data-axis=row]')"))
        assert js("(()=>{const d=document.querySelector('.lookup-grid-divider[data-axis=column]'),s=getComputedStyle(d,'::after');return Math.abs(parseFloat(s.height)/d.getBoundingClientRect().height-.75)<.01;})()")
        assert js("(()=>{const segments=[...document.querySelector('.lookup-grid-divider[data-axis=row]').children];return segments.length===motion.lookup_grid[0].length&&segments.every((segment,column)=>{const line=segment.getBoundingClientRect(),search=lookupCells.get(motion.lookup_grid[0][column]).root.querySelector('.searchbar').getBoundingClientRect();return Math.abs(line.left-search.left)<1&&Math.abs(line.right-search.right)<1;});})()")
        window.web.grab().save('/tmp/ukijiten-character-dividers.png')

        window.open_settings()
        wait_until(lambda:js("!!document.querySelector('[data-section]')"))
        assert not js("!!document.getElementById('game-library-button')")
        assert not js("!!document.querySelector('[data-setting=game_launcher_enabled]')")
        # Image controls hide without deleting sources; removal clears them without merging panes.
        window.set_background(str(gif));window.open_settings()
        wait_until(lambda:js("!!document.getElementById('background-image-toggle')"))
        saved_background=window.settings['background_image']
        js("document.getElementById('background-image-toggle').click()")
        wait_until(lambda:window.settings['background_hidden'])
        assert window.settings['background_image']==saved_background and window.background_url()==''
        assert floating.load_settings()['background_hidden']
        assert js("panel.classList.contains('background-image-disabled')")
        js("document.getElementById('background-image-toggle').click()")
        wait_until(lambda:not window.settings['background_hidden'])
        assert window.background_url()
        saved_color=window.settings['panel_color']
        js("document.getElementById('remove-background-image').click()")
        wait_until(lambda:window.settings['background_image']=='')
        assert window.settings['background_folder']=='' and window.settings['panel_color']==saved_color
        window.update_preference('avatar',str(gif));window.update_preference('avatar_enabled',True)
        old_sizes=window.splitter.sizes()
        js("document.getElementById('remove-avatar-image').click()")
        wait_until(lambda:window.settings['avatar']=='')
        assert window.settings['avatar_folder']=='' and window.settings['avatar_hidden']
        assert window.settings['avatar_enabled'] and window.avatar.isVisible()
        assert window.splitter.sizes()==old_sizes
        print('Floating UI smoke passed, including statistics, dictionary and settings.')
    finally:
        window.anki_stats_feed.close()
        window.stats_feed.close()
        window.stats_import_pool.shutdown(wait=True)
        feed_server.close()
        if shortcut_client is not None and shortcut_client.poll() is None:
            shortcut_client.terminate();shortcut_client.wait(timeout=5)
        window.secondary_worker.shutdown()
        window.close_extra_lookups()
        window.lookup_worker.shutdown()
        window.hover_worker.shutdown()
        window.character_worker.shutdown()
        window.translator.close()
        window.server.close()
        window.quitting=True
        window.close()
