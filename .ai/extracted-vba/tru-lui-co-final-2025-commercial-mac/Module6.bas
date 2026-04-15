Option Explicit
Sub tachsheet()
Dim wb As Workbook ' luu vao file dich
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String
xPath = Application.ActiveWorkbook.Path
' code vba chay muot hon
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

On Error GoTo lbFinally ' khi co loi xay ra

For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
    sFileName = Sh.Range("Q10") & ".xlsx" ' dat ten file trong o Q8 cua tung sheet
    If Not GetWb(sFileName, wb) Then ' kiem tra xem sfilename co dang mo ko
        Set wb = CreateNewWb(sFileName) 'ham tao workbook, neu chua thif tao file co ten file = i8
    End If
    Sh.Copy wb.Sheets(1) ' copy paste value
    Range("A1:AA500").Select
    Selection.Copy
    Range("A1:AA500").Select
    Selection.PasteSpecial Paste:=xlPasteValues
    Application.CutCopyMode = False ' bo lua chon select di
 
Next Sh

Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName

lbFinally: ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
If Err <> 0 Then
    MsgBox Err.Description, vbCritical
End If

End Sub

Function GetWb(sWbName As String, wb As Workbook) As Boolean
' neu GetWb = true thi WB tro vao workbook co ten o tham so sWbName
' neu GetWb = false thi chua co file co ten
    Dim i As Long
    sWbName = UCase(sWbName)
        For i = 1 To Workbooks.Count
            If UCase(Workbooks(i).Name) = sWbName Then
                GetWb = True
                Set wb = Workbooks(i)
                Exit Function
            End If
         Next i
         
            
End Function

 Function CreateNewWb(sWbName As String) As Workbook
 Dim oldWb As Workbook
 Set oldWb = ActiveWorkbook ' tra ve man hinh workbook cu
 Set CreateNewWb = Workbooks.Add ' tao moi workbook
 CreateNewWb.SaveAs sWbName ' luu ten file theo filename
 oldWb.Activate
 
 End Function
