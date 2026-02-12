# GitLab Issue — Copy-Paste Guide
# ================================
# Each section below = one field of the GitLab issue form.
# Copy the content of each section into the corresponding field.


## ===== TITLE =====

Feature Request: Fix cursor position during drag-zoom (middle-button zoom should lock cursor in place)


## ===== DESCRIPTION =====
## (What is the current behavior and what is the expected behavior?)

### Current behavior

When using **drag-zoom** (holding the middle mouse button and moving the mouse vertically to zoom), the mouse cursor moves freely across the screen during the zoom operation. This makes it difficult to keep track of the zoom focus point and results in a disorienting user experience:

1. The cursor drifts away from the point of interest during zoom
2. When the cursor reaches the screen edge, it wraps to the opposite side (infinite drag), which is visually confusing
3. After releasing the middle button, the cursor ends up at an unexpected position far from where the user started

This behavior occurs in all graphical editors: PCB Editor, Schematic Editor, Footprint Editor, Symbol Editor, and Gerber Viewer.

### Expected behavior

When drag-zooming with the middle mouse button:

1. **The cursor should remain visually fixed** at the position where the middle button was pressed
2. **The view should zoom centered on the cursor position** — the point under the cursor stays stationary on screen
3. **Mouse movement up** = smooth zoom in, **mouse movement down** = smooth zoom out
4. **On release**, the cursor reappears at the same position where it was when the user started zooming

This is the standard behavior in many professional CAD applications (Blender, Fusion 360, SolidWorks) and provides a much more intuitive and predictable zoom experience.

### Proposed fix

The fix modifies the existing `DRAG_ZOOMING` state in `WX_VIEW_CONTROLS` (file: `common/view/wx_view_controls.cpp`). Three changes:

**1. Hide cursor on entering DRAG_ZOOMING** — so the user doesn't see it moving:

```diff
--- a/common/view/wx_view_controls.cpp
+++ b/common/view/wx_view_controls.cpp
@@ -512,6 +495,10 @@ void WX_VIEW_CONTROLS::onButton( wxMouseEvent& aEvent )
             m_zoomStartPoint = m_dragStartPoint;
             setState( DRAG_ZOOMING );
 
+            // Hide the cursor so it appears fixed during drag-zoom
+            m_parentPanel->SetCursor( wxCURSOR_BLANK );
+            KIPLATFORM::UI::InfiniteDragPrepareWindow( m_parentPanel );
+
 #if defined USE_MOUSE_CAPTURE
             if( !m_parentPanel->HasCapture() )
                 m_parentPanel->CaptureMouse();
```

**2. Warp cursor back to start point after each zoom step** — instead of letting it drift:

```diff
@@ -320,22 +320,10 @@ void WX_VIEW_CONTROLS::onMotion( wxMouseEvent& aEvent )
         else if( m_state == DRAG_ZOOMING )
         {
             static bool justWarped = false;
-            int warpY = 0;
-            wxSize parentSize = m_parentPanel->GetClientSize();
-
-            if( y < 0 )
-            {
-                warpY = parentSize.y;
-            }
-            else if( y >= parentSize.y )
-            {
-                warpY = -parentSize.y;
-            }
 
             if( !justWarped )
             {
                 VECTOR2D d = m_dragStartPoint - mousePos;
-                m_dragStartPoint = mousePos;
 
                 double scale = exp( d.y * m_settings.m_zoomSpeed * 0.001 );
 
@@ -343,18 +331,13 @@ void WX_VIEW_CONTROLS::onMotion( wxMouseEvent& aEvent )
 
                 m_view->SetScale( m_view->GetScale() * scale, m_view->ToWorld( m_zoomStartPoint ) );
                 aEvent.StopPropagation();
-            }
 
-            if( warpY )
-            {
-                if( !justWarped )
-                {
-                    KIPLATFORM::UI::WarpPointer( m_parentPanel, x, y + warpY );
-                    m_dragStartPoint += VECTOR2D( 0, warpY );
-                    justWarped = true;
-                }
-                else
-                    justWarped = false;
+                // Warp cursor back to the original zoom start point so it appears fixed
+                KIPLATFORM::UI::WarpPointer( m_parentPanel,
+                                              (int) m_zoomStartPoint.x,
+                                              (int) m_zoomStartPoint.y );
+                m_dragStartPoint = m_zoomStartPoint;
+                justWarped = true;
             }
             else
             {
```

**3. Restore cursor on exiting DRAG_ZOOMING** — separate from DRAG_PANNING case:

```diff
@@ -524,6 +511,22 @@ void WX_VIEW_CONTROLS::onButton( wxMouseEvent& aEvent )
         break;
 
     case DRAG_ZOOMING:
+        if( aEvent.MiddleUp() || aEvent.LeftUp() || aEvent.RightUp() )
+        {
+            setState( IDLE );
+
+            // Restore the default cursor after drag-zoom
+            m_parentPanel->SetCursor( wxCURSOR_DEFAULT );
+            KIPLATFORM::UI::InfiniteDragReleaseWindow();
+
+#if defined USE_MOUSE_CAPTURE
+            if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
+                m_parentPanel->ReleaseMouse();
+#endif
+        }
+
+        break;
+
     case DRAG_PANNING:
```

### Summary of changes

| Change | Location | Lines | Description |
|--------|----------|-------|-------------|
| Hide cursor | `onButton()` entry to DRAG_ZOOMING | +4 | `SetCursor(wxCURSOR_BLANK)` + `InfiniteDragPrepareWindow()` |
| Fix cursor position | `onMotion()` DRAG_ZOOMING branch | +6/-17 | `WarpPointer()` back to `m_zoomStartPoint` after each `SetScale()` |
| Restore cursor | `onButton()` exit from DRAG_ZOOMING | +12 | Separate case with `SetCursor(wxCURSOR_DEFAULT)` + `InfiniteDragReleaseWindow()` |

**Total: 1 file changed, 26 insertions, 23 deletions.**

The existing zoom math (`exp(d.y * zoomSpeed * 0.001)`) and anchor logic (`VIEW::SetScale(scale, anchor)`) are preserved — only cursor visibility and position management are changed.


## ===== STEPS TO REPRODUCE =====

1. Open any PCB file in PCB Editor (or create a new one with some content).
2. Hold the **middle mouse button** and move the mouse **up and down** (this triggers drag-zoom, requires "Middle Button Drag" set to "Zoom" in Preferences → Mouse and Touchpad).
3. Observe: the mouse cursor moves freely during zoom, drifting away from the initial point. When it reaches the screen edge, it wraps to the opposite side.

### Expected after fix:
1. Perform the same drag-zoom gesture.
2. The cursor stays visually fixed at the point where you pressed the middle button.
3. The canvas zooms in/out centered on that point.
4. On release, the cursor is exactly where you started.


## ===== KICAD VERSION =====

```
Application: kicad-cli x86_64 on x86_64

Version: 9.0.7-9.0.7~ubuntu24.04.1, release build

Libraries:
        wxWidgets 3.2.4
        FreeType 2.13.2
        HarfBuzz 8.3.0
        FontConfig 2.15.0
        libcurl/8.5.0 OpenSSL/3.0.13 zlib/1.3 brotli/1.1.0 zstd/1.5.5 libidn2/2.3.7 libpsl/0.21.2 (+libidn2/2.3.7) libssh/0.10.6/openssl/zlib nghttp2/1.59.0 librtmp/2.3 OpenLDAP/2.6.7

Platform: Linux Mint 22.2, 64 bit, Little endian, wxBase, cinnamon, x11

Build Info:
        Date: Jan  1 2026 22:15:57
        wxWidgets: 3.2.4 (wchar_t,wx containers) GTK+ 0.0
        Boost: 1.83.0
        OCC: 7.6.3
        Curl: 8.5.0
        ngspice: 42
        Compiler: GCC 13.3.0 with C++ ABI 1018
        KICAD_IPC_API=ON
```

Tested on 9.0.7 stable. The same code path exists in master.


## ===== ATTACHMENTS =====

# Patch file: SMOOTH_ZOOM_PATCH.diff
# Apply with: cd kicad && patch -p1 < SMOOTH_ZOOM_PATCH.diff
# Build: mkdir build && cd build && cmake .. -G Ninja && ninja pcbnew
