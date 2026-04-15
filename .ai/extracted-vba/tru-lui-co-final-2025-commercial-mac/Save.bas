Option Explicit

Sub Save()
Call unProtected
Dim i, lastRowi, lastRowj As Long
    With ThisWorkbook.Sheets("X-N")
    lastRowi = ThisWorkbook.Sheets("X-N").Range("A4").CurrentRegion.Rows.Count
    
    ' code vba chay muot hon
Application.ScreenUpdating = False ' ko canh bao
Application.DisplayAlerts = False ' ngung update man hinh
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

    For i = 4 To lastRowi
         lastRowj = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).row
        If .Range("V" & i) > 0 Then
            .Range(Cells(i, 1), Cells(i, 22)).Copy
            ThisWorkbook.Sheets("Save").Range("A" & lastRowj + 1).PasteSpecial Paste:=xlPasteValues, _
            operation:=xlNone, skipblanks:=False, Transpose:=False
            Application.CutCopyMode = False
            ' tao them ma de lookup
            ThisWorkbook.Sheets("Save").Range("W" & lastRowj + 1) = _
            ThisWorkbook.Sheets("Save").Range("R" & lastRowj + 1) _
            & ThisWorkbook.Sheets("Save").Range("S" & lastRowj + 1)
        End If
    Next
    .Range("A4:V" & lastRowi).Font.ColorIndex = 1 ' tra ve mau den
    .Range("A4:V" & lastRowi).Interior.Color = RGB(255, 255, 255) ' o mau trang
    .Range("C1") = "" ' tra ve gia tri rong
lbFinally: ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
    End With
Call protected
End Sub

Sub saveArr()
Call unProtected
    Dim wsSource As Worksheet
    Dim wsDest As Worksheet
    Dim sourceArr As Variant ' không có () nghia là mang tinh , dùng de load data vào và cô dinh
    Dim outputArr() As Variant '  có () nghia là mang dong , dùng de load data vào và có the thay doi sau dó xuat ra ket qua
    Dim lastRowi As Long
    Dim pasteRow As Long
    Dim i As Long
    Dim outRow As Long
    
    Set wsSource = ThisWorkbook.Sheets("X-N") ' ?? S?a dúng tên sheet
    Set wsDest = ThisWorkbook.Sheets("Save")
    
Application.ScreenUpdating = False ' ko canh bao
Application.DisplayAlerts = False ' ngung update man hinh
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

     ' bo loc,filter,search
     'Call unHide
    
    ' Xác dinh vùng du lieu nguon
    With wsSource
        lastRowi = .Cells(.Rows.Count, "A").End(xlUp).row
        sourceArr = .Range("A4:V" & lastRowi).Value ' Đoc tu ḍng 4 den lastRowi, cot A den V
    End With
    
    ' Đem so ḍng thoa dieu kien de xác dinh kích thuoc outputArr
    Dim cnt As Long
    cnt = 0
    For i = 1 To UBound(sourceArr, 1)
        If sourceArr(i, 22) > 0 Then cnt = cnt + 1 ' Cot V là cot 22
    Next i
    
    If cnt = 0 Then
        MsgBox "Không có data thoa dieu kien!", vbInformation
        GoTo CleanUp
    End If
    
    ' Khoi tao mang outputArr de l?n: (cnt ḍng, 23 côt: A-V + W)
    ReDim outputArr(1 To cnt, 1 To 23) ' su dung redim de update gia tri moi cho mang dong outputArr
    
    ' Ghi du lieu thoa dieu kien vào outputArr
    Dim Tongsldung As Double
    outRow = 1
    Tongsldung = 0
    For i = 1 To UBound(sourceArr, 1)
        If sourceArr(i, 22) > 0 Then
            ' Copy côt A -> V
            Dim j As Long
            For j = 1 To 22
                outputArr(outRow, j) = sourceArr(i, j)
            Next j
            Tongsldung = Tongsldung + sourceArr(i, 22)
            
            ' Tao mă nôi côt R và S (côt 18 và 19)
            outputArr(outRow, 23) = sourceArr(i, 18) & sourceArr(i, 19)
            outRow = outRow + 1
        End If
    Next i
    
    ' Ghi mang outputArr ra sheet "Save"
    pasteRow = wsDest.Cells(wsDest.Rows.Count, "A").End(xlUp).row + 1
    wsDest.Range("A" & pasteRow).Resize(UBound(outputArr, 1), UBound(outputArr, 2)).Value = outputArr
    wsDest.Range("A2:W" & pasteRow + cnt).WrapText = False
    
    'ktra doi chieu tông sl dùng save & XN
    If Tongsldung = wsSource.Range("V1") Then
        MsgBox "SL su dung cua Save khop! " & Tongsldung, vbInformation
    Else
        MsgBox "SL su dung cua Save không khop, Hay kiem tra lai nhé! " & Tongsldung, vbInformation
    End If
    
    
Call truLuiArr ' goi sub tru lui vào trong save

CleanUp:
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
 Call protected
End Sub



Sub savePdf()
Dim sFileName, xPath As String
Dim Sh As Worksheet

xPath = Application.ActiveWorkbook.Path
For Each Sh In ActiveWindow.SelectedSheets
    sFileName = "PDF" & Sh.Range("E4")
    ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, IgnorePrintAreas:=False, _
    fileName:=xPath & "\" & sFileName
Next Sh
End Sub
