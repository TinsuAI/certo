'****************************************
'Tac gia : Nguyen Duy Tuan
'Tel : 0904.210.337
'Email : tuanktcdcn@yahoo.com OR duytuan@bluesofts.net
'Website : www.bluesofts.net
'Khoa hoc VBA nang cao Level1: https://bluesofts.net/daotaothuchanh/dao-tao-vba-trong-excel-nang-cao.html
'Khoa hoc VBA nang cao Level2: https://bluesofts.net/daotaothuchanh/dao-tao-vba-trong-excel-nang-cao-level2.html
'****************************************
Option Explicit
' Declare Window API functions and constants
#If VBA7 Then
Private Declare PtrSafe Function UnhookWindowsHookEx Lib "user32" (ByVal hHook As LongPtr) As Long
Private Declare PtrSafe Function GetCurrentThreadId Lib "kernel32" () As Long
Private Declare PtrSafe Function SetWindowsHookEx Lib "user32" Alias "SetWindowsHookExA" (ByVal idHook As Long, ByVal lpfn As LongPtr, ByVal hmod As LongPtr, ByVal dwThreadId As Long) As LongPtr
Private Declare PtrSafe Function SetWindowPos Lib "user32" (ByVal hwnd As LongPtr, ByVal hWndInsertAfter As LongPtr, ByVal x As Long, ByVal y As Long, ByVal cx As Long, ByVal cy As Long, ByVal wFlags As Long) As Long
Private Declare PtrSafe Function GetClassName Lib "user32.dll" Alias "GetClassNameA" (ByVal hwnd As LongPtr, ByVal lpClassName As String, ByVal nMaxCount As Long) As Long
Private Declare PtrSafe Function MessageBox Lib "user32.dll" Alias "MessageBoxW" (ByVal hwnd As LongPtr, ByVal lpText As String, ByVal lpCaption As String, ByVal wType As Long) As Long
Private Declare PtrSafe Function FindWindow Lib "user32" Alias "FindWindowA" (ByVal lpClassName As String, ByVal lpWindowName As String) As LongPtr
Private Declare PtrSafe Function GetActiveWindow Lib "user32.dll" () As LongPtr
Private Declare PtrSafe Function GetDesktopWindow Lib "user32" () As LongPtr
Private Declare PtrSafe Function GetClientRect Lib "user32" (ByVal hwnd As LongPtr, lpRect As RECT) As Long
Private Declare PtrSafe Function GetWindowRect Lib "user32" (ByVal hwnd As LongPtr, lpRect As RECT) As Long
Private Declare PtrSafe Function GetSystemMetrics Lib "user32" (ByVal nIndex As Long) As Long
' Handle to the Hook procedure
Private hHook As LongPtr
#Else
Private Declare Function UnhookWindowsHookEx Lib "user32" (ByVal hHook As Long) As Long
Private Declare Function GetCurrentThreadId Lib "kernel32" () As Long
Private Declare Function SetWindowsHookEx Lib "user32" Alias "SetWindowsHookExA" (ByVal idHook As Long, ByVal lpfn As Long, ByVal hmod As Long, ByVal dwThreadId As Long) As Long
Private Declare Function SetWindowPos Lib "user32" (ByVal hwnd As Long, ByVal hWndInsertAfter As Long, ByVal x As Long, ByVal y As Long, ByVal cx As Long, ByVal cy As Long, ByVal wFlags As Long) As Long
Private Declare Function GetClassName Lib "user32.dll" Alias "GetClassNameA" (ByVal hwnd As Long, ByVal lpClassName As String, ByVal nMaxCount As Long) As Long
Private Declare Function MessageBox Lib "user32.dll" Alias "MessageBoxW" (ByVal hwnd As Long, ByVal lpText As String, ByVal lpCaption As String, ByVal wType As Long) As Long
Private Declare Function FindWindow Lib "user32" Alias "FindWindowA" (ByVal lpClassName As String, ByVal lpWindowName As String) As Long
Private Declare Function GetActiveWindow Lib "user32.dll" () As Long
Private Declare Function GetDesktopWindow Lib "user32" () As Long
Private Declare Function GetClientRect Lib "user32" (ByVal hwnd As Long, lpRect As RECT) As Long
Private Declare Function GetWindowRect Lib "user32" (ByVal hwnd As Long, lpRect As RECT) As Long
Private Declare Function GetSystemMetrics Lib "user32" (ByVal nIndex As Long) As Long
'Handle to the Hook procedure
Private hHook As Long
#End If
Private Type RECT
   Left As Long
   Top As Long
   Right As Long
   Bottom As Long
End Type
Private Const SM_CXBORDER = 5
Private Const SM_CYBORDER = 6
Private Const SM_CXEDGE = 45
Private Const SM_CYEDGE = 46
Private Const SM_CXFRAME = &H20
Private Const SM_CYFRAME = 33
'Hook type
Private Const WH_CBT = 5
Private Const HCBT_ACTIVATE = 5
'SetWindowPos Flags
Private Const SWP_NOSIZE = &H1
Private Const SWP_NOZORDER = &H4
'Position for UniMsgBoxPos
Private msgbox_x As Long
Private msgbox_y As Long
'Position Flags for UniMsgBoxPos
Const POS_RIGHT = 10000
Const POS_BOTTOM = 10000
Const POS_CENTER_X = -1
Const POS_CENTER_Y = -1
'SOURCE CODE for UniMsgBoxPos
'Created by: Nguyen Duy Tuan
Public Function UniMsgBoxPos(strPromt As String, Optional vbButtons As VbMsgBoxStyle = vbOKOnly, Optional strTitle As String = "", Optional xPos As Long = -1, Optional yPos As Long = -1)
   ' Store position
   msgbox_x = xPos
   msgbox_y = yPos
   ' Set Hook
   hHook = SetWindowsHookEx(WH_CBT, AddressOf MsgBoxHookProc, 0, GetCurrentThreadId)
   ' Run MessageBox
   'Modified by Nguyen Duy Tuan
   UniMsgBoxPos = MessageBox(GetActiveWindow, StrConv(strPromt, vbUnicode), StrConv(IIf(strTitle = "", Application.Name, strTitle), vbUnicode), vbButtons)
'MsgBox for unicode basic here:
   'https://bluesofts.net/Lap-trinh-VBA/co-ban/Hien-thi-MsgBox-chu-co-dau-tieng-viet---Unicode
   If hHook <> 0 Then  ' Release the Hook again (important!)
      UnhookWindowsHookEx hHook
   End If
End Function
#If VBA7 Then
Private Function MsgBoxHookProc(ByVal lMsg As Long, ByVal wParam As LongPtr, ByVal lParam As LongPtr) As LongPtr
   #Else
   Private Function MsgBoxHookProc(ByVal lMsg As Long, ByVal wParam As Long, ByVal lParam As Long) As Long
      #End If
      If lMsg = HCBT_ACTIVATE Then
         'Modified by Nguyen Duy Tuan
         'Begin checking class for MsgBox Window
         'wParam is the handle of MsgBox (Window)
         Dim sClsName As String
         Dim x&, y&, rc As RECT, rc2 As RECT, rc3 As RECT
         Dim hd, hWndTray
         sClsName = Space(32)
         x = GetClassName(wParam, sClsName, 32)
         sClsName = Left(sClsName, x)  'string convertion
         If sClsName = "#32770" Then  'Active Window Is MsgBox
            hd = GetDesktopWindow
            hWndTray = FindWindow("Shell_TrayWnd", vbNullString)
            GetWindowRect hWndTray, rc3  'SysTray
            GetClientRect hd, rc2  'Desktop
            GetWindowRect wParam, rc  'MsgBox
            x = msgbox_x: y = msgbox_y
            If msgbox_x = POS_CENTER_X Or msgbox_y = POS_CENTER_Y Then
               If msgbox_x = POS_CENTER_X Then
                  x = ((rc2.Right - rc2.Left) - (rc.Right - rc.Left)) \ 2
               End If
               If msgbox_y = POS_CENTER_Y Then
                  y = ((rc2.Bottom - rc2.Top) - (rc.Bottom - rc.Top)) \ 2
               End If
            End If
            If msgbox_x = POS_RIGHT Then
               x = rc2.Right - (rc.Right - rc.Left) + GetSystemMetrics(SM_CXBORDER) + GetSystemMetrics(SM_CXEDGE) + GetSystemMetrics(SM_CXFRAME)
            End If
            If msgbox_y = POS_BOTTOM Then
               y = rc2.Bottom - (rc.Bottom - rc.Top)
            End If
            If msgbox_y = POS_BOTTOM Or msgbox_y = POS_CENTER_Y Then
               y = y - GetSystemMetrics(SM_CYBORDER) + GetSystemMetrics(SM_CYEDGE) + GetSystemMetrics(SM_CYFRAME) - (rc3.Bottom - rc3.Top)
            End If
            If msgbox_x = 0 Then
               x = x - GetSystemMetrics(SM_CXBORDER) - GetSystemMetrics(SM_CXEDGE) - GetSystemMetrics(SM_CXFRAME)
            End If
            'Change position
            SetWindowPos wParam, 0, x, y, 0, 0, SWP_NOSIZE + SWP_NOZORDER
            'Release the Hook
            UnhookWindowsHookEx hHook
            hHook = 0
            MsgBoxHookProc = True
            Exit Function
         End If
      End If
      MsgBoxHookProc = False
End Function
