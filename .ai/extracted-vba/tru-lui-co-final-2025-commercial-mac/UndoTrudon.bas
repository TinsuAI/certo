Sub Undo()
    Dim lookupRange As Range 'tao bien r chay
    Dim i, j, k, hang, cot, lastRow, lastRow2 As Integer
    Dim answer As Integer
    With ThisWorkbook.Sheets("NK2")
    lastRow = ThisWorkbook.Sheets("NK2").Cells(.Rows.Count, "A").End(xlUp).row
    lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
    Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:X" & lastRow2)
    
    Application.ScreenUpdating = False ' ngung update man hinh
    Application.DisplayAlerts = False ' ko canh bao
    Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel
 
    answer = MsgBox("Do you want to proceed that ?", vbYesNo) ' hien thi yes/no
        Select Case answer
            Case vbYes
' tao cot phu
            For i = 5 To lastRow
                .Range("W" & i) = .Range("A" & i).Value & .Range("D" & i).Value & _
                .Range("E" & i).Value & .Range("V3").Value ' ma cot phu o NK2
            Next
        
' tao cot phu
            For j = 2 To lastRow2
                If ThisWorkbook.Sheets("Save").Range("R" & j) = .Range("V3") Then
                    ThisWorkbook.Sheets("Save").Range("X" & j) = ThisWorkbook.Sheets("Save").Range("A" & j).Value & _
                    ThisWorkbook.Sheets("Save").Range("D" & j).Value & ThisWorkbook.Sheets("Save").Range("E" & j).Value & _
                    ThisWorkbook.Sheets("Save").Range("R" & j).Value ' ma cot phu o save
                End If
            Next
        
            cot = Application.Match(.Range("V4"), ThisWorkbook.Sheets("Save").Range("A1:X1"), 0)
            For k = 5 To lastRow '  Application bay loi khi khong tim thay gia tri
                hang = Application.Match(.Range("W" & k), ThisWorkbook.Sheets("Save").Range("X2:X" & lastRow2), 0)
                .Range("V" & k) = Application.Index(lookupRange, hang, cot) ' dung ham index& march de lay data
                .Range("V" & k).Replace "#N/A", "", xlWhole ' thay the loi type mismatch #NA
            Next
        ' xoa
            ThisWorkbook.Sheets("Save").Range("X2:X" & lastRow2) = ""
            .Range("W5:W" & lastRow) = ""
        
            Case vbNo
                MsgBox ("OK!")
            
        End Select

lbFinally:            ' hoan tra ve ban dat
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic

    End With

End Sub


Sub UndoArr()
    Dim wsNK2 As Worksheet, wsSave As Worksheet
    Dim dataNK2 As Variant, dataSave As Variant
    Dim i As Long, j As Long, k As Long
    Dim lastRowNK2 As Long, lastRowSave As Long
    Dim answer As VbMsgBoxResult
    Dim helperNK2() As String, helperSave() As String
    Dim colResult As Long
    Dim dictSave As Object
    Dim key As String
    Dim resultArr() As Variant

    Set wsNK2 = ThisWorkbook.Sheets("NK2")
    Set wsSave = ThisWorkbook.Sheets("Save")

    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual

    answer = MsgBox("Do you want to proceed that ?", vbYesNo)
    If answer = vbNo Then
        MsgBox "OK!"
        GoTo lbFinally
    End If

    ' Xác d?nh hàng cu?i
    lastRowNK2 = wsNK2.Cells(wsNK2.Rows.Count, "A").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row

    ' Đ?c d? li?u vào m?ng
    dataNK2 = wsNK2.Range("A5:V" & lastRowNK2).Value
    dataSave = wsSave.Range("A2:X" & lastRowSave).Value
    ReDim helperNK2(1 To UBound(dataNK2, 1))
    ReDim helperSave(1 To UBound(dataSave, 1))
    ReDim resultArr(1 To UBound(dataNK2, 1), 1 To 1)

    ' T?o c?t ph? NK2 (W = A & D & E & V3)
    Dim v3Value As String
    v3Value = wsNK2.Range("V3").Value
    For i = 1 To UBound(dataNK2, 1)
        helperNK2(i) = CStr(dataNK2(i, 1) & dataNK2(i, 4) & dataNK2(i, 5) & v3Value)
    Next i

    ' T?o c?t ph? Save (X = A & D & E & R n?u R = V3)
    For j = 1 To UBound(dataSave, 1)
        If dataSave(j, 18) = v3Value Then ' c?t R = 18
            helperSave(j) = dataSave(j, 1) & dataSave(j, 4) & dataSave(j, 5) & dataSave(j, 18)
        Else
            helperSave(j) = ""
        End If
    Next j

    ' T?o Dictionary cho lookup
    Set dictSave = CreateObject("Scripting.Dictionary")
    colResult = Application.Match(wsNK2.Range("V4").Value, wsSave.Range("A1:X1"), 0)
    If IsError(colResult) Then
        MsgBox "Không t́m th?y tiêu d? c?n tra c?u!", vbExclamation
        GoTo lbFinally
    End If

    For j = 1 To UBound(helperSave)
        If helperSave(j) <> "" And Not dictSave.Exists(helperSave(j)) Then
            dictSave.Add helperSave(j), dataSave(j, colResult)
        End If
    Next j

    ' T́m giá tr? tuong ?ng và gán vào m?ng k?t qu?
    For i = 1 To UBound(helperNK2)
        key = helperNK2(i)
        If dictSave.Exists(key) Then
            resultArr(i, 1) = dictSave(key)
        Else
            resultArr(i, 1) = ""
        End If
    Next i

    ' Ghi k?t qu? ra c?t V (col 22)
    wsNK2.Range("V5").Resize(UBound(resultArr), 1).Value = resultArr

    ' Xóa d? li?u c?t ph?
    wsSave.Range("X2:X" & lastRowSave).ClearContents
    wsNK2.Range("W5:W" & lastRowNK2).ClearContents
    
    

lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationSemiautomatic
End Sub




Sub truDon()
Dim i, lastRow As Integer
Dim answer As Integer
lastRow = ThisWorkbook.Sheets("NK2").Range("A5").CurrentRegion.Rows.Count
With ThisWorkbook.Sheets("NK2")
Application.ScreenUpdating = False ' ko canh bao
Application.DisplayAlerts = False ' ngung update man hinh
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

answer = MsgBox("Do you want to proceed that ?", vbYesNo) ' hien thi yes/no
    Select Case answer
        Case vbYes
            For i = 5 To lastRow
                If .Range("V" & i) <> 0 Or .Range("V" & i) <> "" Then
                    .Range("Q" & i) = .Range("Q" & i) - .Range("V" & i)
                End If
            Next
            .Range("V5:V" & lastRow) = ""
        Case vbNo
            MsgBox ("OK!")
    End Select
    
    Call deleteXN
    Call deleteDM
    
    
lbFinally:    ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

End With

End Sub




Sub truDonArr()
    Dim ws As Worksheet
    Dim data As Variant
    Dim i As Long
    Dim lastRow As Long
    Dim answer As VbMsgBoxResult

    Set ws = ThisWorkbook.Sheets("NK2")
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual

    answer = MsgBox("Do you want to proceed that ?", vbYesNo)
    If answer = vbNo Then
        MsgBox "OK!"
        GoTo lbFinally
    End If

    ' Xác d?nh s? ḍng
    lastRow = ws.Range("A5").CurrentRegion.Rows.Count
    If lastRow < 5 Then GoTo lbFinally ' không có d? li?u

    ' Đ?c d? li?u t? c?t Q và V vào m?ng (t? hàng 5)
    data = ws.Range("Q5:V" & lastRow).Value

    ' data là m?ng 1 to N, 1 to 6 (Q=1, ..., V=6)
    For i = 1 To UBound(data, 1)
        If IsNumeric(data(i, 6)) And data(i, 6) <> 0 Then
            data(i, 1) = Round(data(i, 1) - data(i, 6), 2) ' Q = Q - V
            data(i, 6) = "" ' Xóa V sau khi tr?
        End If
    Next i

    ' Ghi l?i k?t qu? v? worksheet
    ws.Range("Q5:Q" & lastRow).Value = data
    
    ws.Range("V5:V" & lastRow) = ""
    
    Call deleteXN
    Call deleteDM

lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationSemiautomatic
End Sub
